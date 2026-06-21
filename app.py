"""Direct ZIP to GitHub Streamlit uploader.

This app lets a non-technical user upload a .zip project and push the
extracted files straight to GitHub with one button. It uses the GitHub Git
Database API so a whole project can be committed as one clean commit.
"""

from __future__ import annotations

import base64
import csv
import io
import os
import posixpath
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests
import streamlit as st


APP_VERSION = "3.0.0"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_API_BASE = "https://api.github.com"
MAX_GITHUB_FILE_BYTES = 100 * 1024 * 1024
SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")
SAFE_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__MACOSX",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "bower_components",
    "vendor",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
    "coverage",
    "htmlcov",
}

DEFAULT_IGNORE_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".streamlit/secrets.toml",
    "secrets.toml",
    "id_rsa",
    "id_ed25519",
}

TEXT_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".csv",
    ".ini",
    ".cfg",
    ".gitignore",
    ".html",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
    ".dockerfile",
}


@dataclass(frozen=True)
class RepoFile:
    archive_path: str
    repo_path: str
    content: bytes
    source: str

    @property
    def size_bytes(self) -> int:
        return len(self.content)


@dataclass
class ZipBuildResult:
    files: List[RepoFile]
    skipped: List[Tuple[str, str]]
    removed_root: str
    total_archive_entries: int
    total_uncompressed_bytes: int


@dataclass
class BranchState:
    branch: str
    commit_sha: Optional[str]
    tree_sha: Optional[str]
    ref_exists: bool
    empty_repo: bool


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns a failure response."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class GitHubClient:
    def __init__(self, token: str, owner: str, repo: str, api_base: str = DEFAULT_API_BASE):
        self.token = token.strip()
        self.owner = owner.strip()
        self.repo = repo.strip()
        self.api_base = api_base.rstrip("/")

        if not self.token:
            raise ValueError("GitHub token is required in the sidebar.")
        if not self.owner:
            raise ValueError("Repository owner is required in the sidebar.")
        if not self.repo:
            raise ValueError("Repository name is required in the sidebar.")
        if not SAFE_REPO_RE.match(self.repo):
            raise ValueError("Repository name can only use letters, numbers, dots, dashes, and underscores.")

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    def _url(self, path: str) -> str:
        return f"{self.api_base}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", 90)
        return requests.request(method, self._url(path), headers=self.headers, timeout=timeout, **kwargs)

    def _json_or_text(self, resp: requests.Response) -> Dict[str, Any]:
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                return payload
            return {"message": str(payload)[:1000]}
        except Exception:
            return {"message": resp.text[:1000]}

    def _raise(self, resp: requests.Response, fallback: str) -> None:
        payload = self._json_or_text(resp)
        api_message = payload.get("message") or fallback
        raise GitHubAPIError(f"{fallback} GitHub said: {api_message}", resp.status_code, payload)

    def me(self) -> Dict[str, Any]:
        resp = self._request("GET", "/user")
        if resp.status_code >= 400:
            self._raise(resp, "Could not read the authenticated GitHub user.")
        return resp.json()

    def get_repo(self) -> Optional[Dict[str, Any]]:
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            self._raise(resp, "Could not access the repository.")
        return resp.json()

    def ensure_repo(self, *, create_if_missing: bool, private: bool, description: str) -> Dict[str, Any]:
        repo_info = self.get_repo()
        if repo_info:
            return repo_info

        if not create_if_missing:
            raise GitHubAPIError(
                f"Repository {self.owner}/{self.repo} was not found. Turn on 'Create repo if missing' or create it first."
            )

        user = self.me()
        login = user.get("login", "")
        body = {
            "name": self.repo,
            "private": private,
            "description": description,
            "auto_init": False,
        }

        if self.owner.lower() == str(login).lower():
            resp = self._request("POST", "/user/repos", json=body, timeout=120)
        else:
            resp = self._request("POST", f"/orgs/{self.owner}/repos", json=body, timeout=120)

        if resp.status_code >= 400:
            self._raise(resp, "Could not create the repository.")
        return resp.json()

    def get_ref(self, branch: str) -> Optional[Dict[str, Any]]:
        encoded_branch = quote(branch, safe="/")
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}/git/ref/heads/{encoded_branch}")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            self._raise(resp, f"Could not read branch ref: {branch}")
        return resp.json()

    def create_ref(self, branch: str, commit_sha: str) -> Dict[str, Any]:
        body = {"ref": f"refs/heads/{branch}", "sha": commit_sha}
        resp = self._request("POST", f"/repos/{self.owner}/{self.repo}/git/refs", json=body, timeout=120)
        if resp.status_code >= 400:
            self._raise(resp, f"Could not create branch: {branch}")
        return resp.json()

    def update_ref(self, branch: str, commit_sha: str, *, force: bool) -> Dict[str, Any]:
        encoded_branch = quote(branch, safe="/")
        body = {"sha": commit_sha, "force": force}
        resp = self._request(
            "PATCH",
            f"/repos/{self.owner}/{self.repo}/git/refs/heads/{encoded_branch}",
            json=body,
            timeout=120,
        )
        if resp.status_code >= 400:
            self._raise(resp, f"Could not update branch ref: {branch}")
        return resp.json()

    def get_commit(self, commit_sha: str) -> Dict[str, Any]:
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}/git/commits/{commit_sha}")
        if resp.status_code >= 400:
            self._raise(resp, f"Could not read commit: {commit_sha}")
        return resp.json()

    def get_tree(self, tree_sha: str, *, recursive: bool = False) -> Dict[str, Any]:
        params = {"recursive": "1"} if recursive else None
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}/git/trees/{tree_sha}", params=params, timeout=120)
        if resp.status_code >= 400:
            self._raise(resp, "Could not read Git tree.")
        return resp.json()

    def get_branch_state(self, branch: str, repo_info: Dict[str, Any], *, create_branch_from_default: bool) -> BranchState:
        ref = self.get_ref(branch)
        if ref:
            commit_sha = ref.get("object", {}).get("sha")
            if not commit_sha:
                raise GitHubAPIError(f"Branch {branch} exists but GitHub did not return a commit SHA.")
            commit = self.get_commit(commit_sha)
            tree_sha = commit.get("tree", {}).get("sha")
            if not tree_sha:
                raise GitHubAPIError(f"Could not find the tree for branch {branch}.")
            return BranchState(branch=branch, commit_sha=commit_sha, tree_sha=tree_sha, ref_exists=True, empty_repo=False)

        default_branch = repo_info.get("default_branch") or "main"
        default_ref = self.get_ref(default_branch)
        if default_ref:
            if not create_branch_from_default and branch != default_branch:
                raise GitHubAPIError(f"Branch {branch} does not exist. Turn on 'Create branch if missing'.")
            default_commit_sha = default_ref.get("object", {}).get("sha")
            commit = self.get_commit(default_commit_sha)
            tree_sha = commit.get("tree", {}).get("sha")
            return BranchState(branch=branch, commit_sha=default_commit_sha, tree_sha=tree_sha, ref_exists=False, empty_repo=False)

        # Empty newly-created repo: no branch/ref exists yet.
        return BranchState(branch=branch, commit_sha=None, tree_sha=None, ref_exists=False, empty_repo=True)

    def create_blob(self, content: bytes) -> str:
        body = {"content": base64.b64encode(content).decode("utf-8"), "encoding": "base64"}
        resp = self._request("POST", f"/repos/{self.owner}/{self.repo}/git/blobs", json=body, timeout=180)
        if resp.status_code >= 400:
            self._raise(resp, "Could not create a Git blob.")
        sha = resp.json().get("sha")
        if not sha:
            raise GitHubAPIError("GitHub did not return a blob SHA.")
        return sha

    def create_tree(self, tree_items: List[Dict[str, Any]], *, base_tree_sha: Optional[str]) -> str:
        body: Dict[str, Any] = {"tree": tree_items}
        if base_tree_sha:
            body["base_tree"] = base_tree_sha
        resp = self._request("POST", f"/repos/{self.owner}/{self.repo}/git/trees", json=body, timeout=180)
        if resp.status_code >= 400:
            self._raise(resp, "Could not create the Git tree.")
        sha = resp.json().get("sha")
        if not sha:
            raise GitHubAPIError("GitHub did not return a tree SHA.")
        return sha

    def create_commit(
        self,
        *,
        message: str,
        tree_sha: str,
        parent_sha: Optional[str],
        committer_name: Optional[str],
        committer_email: Optional[str],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"message": message, "tree": tree_sha, "parents": [parent_sha] if parent_sha else []}
        if committer_name and committer_email:
            person = {"name": committer_name, "email": committer_email}
            body["author"] = person
            body["committer"] = person
        resp = self._request("POST", f"/repos/{self.owner}/{self.repo}/git/commits", json=body, timeout=180)
        if resp.status_code >= 400:
            self._raise(resp, "Could not create the Git commit.")
        payload = resp.json()
        if not payload.get("sha"):
            raise GitHubAPIError("GitHub did not return a commit SHA.")
        return payload

    def direct_push(
        self,
        *,
        files: Sequence[RepoFile],
        branch: str,
        commit_message: str,
        repo_info: Dict[str, Any],
        overwrite_existing: bool,
        create_branch_if_missing: bool,
        clean_target_folder: bool,
        target_folder: str,
        force_ref_update: bool,
        committer_name: Optional[str],
        committer_email: Optional[str],
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> Dict[str, Any]:
        if not files:
            raise ValueError("No files were available to upload after ZIP filtering.")

        state = self.get_branch_state(branch, repo_info, create_branch_from_default=create_branch_if_missing)
        existing_paths: set[str] = set()

        if state.tree_sha:
            if progress:
                progress(0.02, "Reading current repository tree…")
            tree = self.get_tree(state.tree_sha, recursive=True)
            existing_paths = {
                item.get("path", "")
                for item in tree.get("tree", [])
                if item.get("type") == "blob" and item.get("path")
            }

        upload_files: List[RepoFile] = []
        skipped_existing: List[str] = []
        for file in files:
            if file.repo_path in existing_paths and not overwrite_existing and not clean_target_folder:
                skipped_existing.append(file.repo_path)
            else:
                upload_files.append(file)

        upload_paths = {file.repo_path for file in upload_files}
        delete_items: List[Dict[str, Any]] = []
        if state.tree_sha and clean_target_folder:
            prefix = sanitize_folder(target_folder)
            if prefix:
                delete_candidates = sorted(path for path in existing_paths if path == prefix or path.startswith(prefix + "/"))
            else:
                delete_candidates = sorted(existing_paths)
            # Do not add a delete entry for a path that is being replaced in the same tree.
            # The new blob entry already overwrites that path.
            delete_items = [
                {"path": path, "mode": "100644", "type": "blob", "sha": None}
                for path in delete_candidates
                if path not in upload_paths
            ]

        if not upload_files and not delete_items:
            return {
                "status": "nothing_to_commit",
                "message": "All files already exist and overwrite is off.",
                "files_uploaded": 0,
                "files_skipped_existing": len(skipped_existing),
                "files_deleted_first": 0,
                "commit_sha": "",
                "commit_url": "",
                "tree_url": repo_tree_url(self.owner, self.repo, branch, target_folder),
            }

        tree_items: List[Dict[str, Any]] = []
        tree_items.extend(delete_items)

        total = len(upload_files)
        for idx, file in enumerate(upload_files, start=1):
            if file.size_bytes > MAX_GITHUB_FILE_BYTES:
                raise GitHubAPIError(f"GitHub rejects files larger than 100 MB: {file.repo_path}")
            if progress:
                progress(0.05 + (idx / max(total, 1)) * 0.72, f"Uploading file data {idx}/{total}: {file.repo_path}")
            blob_sha = self.create_blob(file.content)
            tree_items.append({"path": file.repo_path, "mode": "100644", "type": "blob", "sha": blob_sha})

        if progress:
            progress(0.82, "Creating one Git tree for the whole project…")
        new_tree_sha = self.create_tree(tree_items, base_tree_sha=state.tree_sha)

        if progress:
            progress(0.90, "Creating one commit…")
        commit = self.create_commit(
            message=commit_message,
            tree_sha=new_tree_sha,
            parent_sha=state.commit_sha,
            committer_name=committer_name,
            committer_email=committer_email,
        )
        commit_sha = commit["sha"]

        if progress:
            progress(0.97, "Moving the GitHub branch to the new commit…")
        if state.ref_exists:
            self.update_ref(branch, commit_sha, force=force_ref_update)
        else:
            self.create_ref(branch, commit_sha)

        if progress:
            progress(1.0, "Upload complete.")

        return {
            "status": "committed",
            "message": commit_message,
            "files_uploaded": len(upload_files),
            "files_skipped_existing": len(skipped_existing),
            "files_deleted_first": len(delete_items),
            "commit_sha": commit_sha,
            "commit_url": f"https://github.com/{self.owner}/{self.repo}/commit/{commit_sha}",
            "tree_url": repo_tree_url(self.owner, self.repo, branch, target_folder),
        }


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)  # type: ignore[attr-defined]
        return str(value) if value is not None else default
    except Exception:
        return default


def quote_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in path.split("/"))


def repo_tree_url(owner: str, repo: str, branch: str, target_folder: str = "") -> str:
    branch_part = quote(branch, safe="/")
    folder = sanitize_folder(target_folder)
    if folder:
        return f"https://github.com/{owner}/{repo}/tree/{branch_part}/{quote_path(folder)}"
    return f"https://github.com/{owner}/{repo}/tree/{branch_part}"


def sanitize_folder(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip().strip("/")
    if not value:
        return ""
    normalized = posixpath.normpath(value).replace("\\", "/")
    if normalized in (".", ""):
        return ""
    if normalized.startswith("../") or normalized == ".." or "/../" in normalized:
        raise ValueError(f"Unsafe target folder rejected: {value}")
    if normalized.startswith("/"):
        raise ValueError(f"Unsafe absolute target folder rejected: {value}")
    return normalized


def safe_repo_path(path: str) -> str:
    path = str(path or "").replace("\\", "/").strip().strip("/")
    normalized = posixpath.normpath(path).replace("\\", "/")
    if normalized in (".", ""):
        raise ValueError("File path cannot be empty.")
    if normalized.startswith("../") or normalized == ".." or "/../" in normalized:
        raise ValueError(f"Unsafe path rejected: {path}")
    if normalized.startswith("/"):
        raise ValueError(f"Unsafe absolute path rejected: {path}")
    return normalized


def combine_repo_path(target_folder: str, relative_path: str, *, flatten: bool = False) -> str:
    relative_path = str(relative_path or "").replace("\\", "/").strip("/")
    if flatten:
        relative_path = relative_path.split("/")[-1]
    folder = sanitize_folder(target_folder)
    return safe_repo_path(f"{folder}/{relative_path}" if folder else relative_path)


def validate_branch(branch: str) -> None:
    if not branch or not SAFE_BRANCH_RE.match(branch):
        raise ValueError("Branch name looks invalid. Use letters, numbers, dashes, underscores, dots, or slashes.")


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    file_type = (info.external_attr >> 16) & 0o170000
    return file_type == 0o120000


def should_ignore_path(path: str, ignore_dirs: set[str], ignore_files: set[str], skip_secrets: bool) -> Tuple[bool, str]:
    clean = path.replace("\\", "/").strip("/")
    if not clean:
        return True, "empty path"
    parts = clean.split("/")
    filename = parts[-1]

    if clean.startswith("__MACOSX/") or "/__MACOSX/" in clean:
        return True, "macOS ZIP metadata"
    if filename in ignore_files or clean in ignore_files:
        return True, "ignored file"
    if filename.endswith((".pyc", ".pyo")):
        return True, "compiled Python cache"
    for part in parts:
        if part in ignore_dirs:
            return True, f"ignored folder: {part}"

    lowered = clean.lower()
    if skip_secrets:
        secret_fragments = [
            ".streamlit/secrets.toml",
            "secrets.toml",
            ".env",
            "private_key",
            "id_rsa",
            "id_ed25519",
            "credentials.json",
            "service-account",
            "service_account",
        ]
        if any(fragment in lowered for fragment in secret_fragments):
            return True, "secret/credential-looking file"
    return False, ""


def parse_ignore_text(value: str) -> Tuple[set[str], set[str]]:
    dirs = set(DEFAULT_IGNORE_DIRS)
    files = set(DEFAULT_IGNORE_FILES)
    for raw in (value or "").splitlines():
        item = raw.strip().strip("/")
        if not item or item.startswith("#"):
            continue
        if "/" in item or "." in os.path.basename(item):
            files.add(item)
        else:
            dirs.add(item)
    return dirs, files


def find_common_root(paths: Sequence[str]) -> str:
    if not paths:
        return ""
    first = paths[0].split("/")[0]
    if not first:
        return ""
    if all(path.startswith(first + "/") for path in paths) and any("/" in path for path in paths):
        return first
    return ""


def strip_common_root(path: str, common_root: str) -> str:
    if common_root and path.startswith(common_root + "/"):
        return path[len(common_root) + 1 :]
    return path


def bytes_label(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def build_zip_files(
    *,
    zip_bytes: bytes,
    zip_name: str,
    target_folder: str,
    strip_top_folder: bool,
    flatten_paths: bool,
    ignore_dirs: set[str],
    ignore_files: set[str],
    skip_secrets: bool,
    max_file_mb: int,
    max_total_mb: int,
    max_files: int,
    include_original_zip: bool,
) -> ZipBuildResult:
    files: List[RepoFile] = []
    skipped: List[Tuple[str, str]] = []
    max_file_bytes = max(1, int(max_file_mb)) * 1024 * 1024
    max_total_bytes = max(1, int(max_total_mb)) * 1024 * 1024
    total_uncompressed = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        infos = zf.infolist()
        valid_archive_paths: List[str] = []

        for info in infos:
            raw = info.filename.replace("\\", "/").strip("/")
            if not raw or info.is_dir():
                continue
            if is_zip_symlink(info):
                skipped.append((raw, "symbolic link skipped"))
                continue
            ignored, reason = should_ignore_path(raw, ignore_dirs, ignore_files, skip_secrets)
            if ignored:
                skipped.append((raw, reason))
                continue
            try:
                safe_repo_path(raw)
            except Exception as exc:
                skipped.append((raw, str(exc)))
                continue
            if info.file_size > max_file_bytes:
                skipped.append((raw, f"file is larger than {max_file_mb} MB"))
                continue
            if info.file_size > MAX_GITHUB_FILE_BYTES:
                skipped.append((raw, "GitHub file limit is 100 MB"))
                continue
            valid_archive_paths.append(raw)
            total_uncompressed += int(info.file_size)

        if len(valid_archive_paths) > max_files:
            raise ValueError(f"ZIP has {len(valid_archive_paths):,} uploadable files. Limit is {max_files:,}.")
        if total_uncompressed > max_total_bytes:
            raise ValueError(
                f"ZIP expands to {bytes_label(total_uncompressed)}, which is over the {max_total_mb} MB safety limit."
            )

        common_root = find_common_root(valid_archive_paths) if strip_top_folder else ""
        seen_repo_paths: set[str] = set()

        for info in infos:
            raw = info.filename.replace("\\", "/").strip("/")
            if not raw or info.is_dir() or is_zip_symlink(info):
                continue
            ignored, _reason = should_ignore_path(raw, ignore_dirs, ignore_files, skip_secrets)
            if ignored:
                continue
            if raw not in valid_archive_paths:
                continue

            rel = strip_common_root(raw, common_root)
            if not rel:
                skipped.append((raw, "top folder only"))
                continue

            try:
                content = zf.read(info)
                repo_path = combine_repo_path(target_folder, rel, flatten=flatten_paths)
            except Exception as exc:
                skipped.append((raw, str(exc)))
                continue

            if repo_path in seen_repo_paths:
                root, ext = os.path.splitext(repo_path)
                repo_path = f"{root}-{len(seen_repo_paths) + 1}{ext}"
            seen_repo_paths.add(repo_path)
            files.append(RepoFile(archive_path=raw, repo_path=repo_path, content=content, source=zip_name))

    if include_original_zip:
        archive_path = combine_repo_path("archives", zip_name, flatten=True)
        files.append(RepoFile(archive_path=zip_name, repo_path=archive_path, content=zip_bytes, source="original ZIP archive"))

    return ZipBuildResult(
        files=files,
        skipped=skipped,
        removed_root=common_root,
        total_archive_entries=len(infos),
        total_uncompressed_bytes=total_uncompressed,
    )


def make_files_from_uploads(uploaded_files: Iterable[Any], target_folder: str, flatten_paths: bool) -> List[RepoFile]:
    files: List[RepoFile] = []
    seen: set[str] = set()
    for item in uploaded_files:
        content = item.getvalue()
        repo_path = combine_repo_path(target_folder, item.name, flatten=flatten_paths)
        if len(content) > MAX_GITHUB_FILE_BYTES:
            raise ValueError(f"GitHub rejects files larger than 100 MB: {item.name}")
        if repo_path in seen:
            root, ext = os.path.splitext(repo_path)
            repo_path = f"{root}-{len(seen) + 1}{ext}"
        seen.add(repo_path)
        files.append(RepoFile(archive_path=item.name, repo_path=repo_path, content=content, source="browser upload"))
    return files


def files_csv(files: Sequence[RepoFile]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["source", "archive_path", "github_path", "size_bytes", "size"])
    writer.writeheader()
    for file in files:
        writer.writerow(
            {
                "source": file.source,
                "archive_path": file.archive_path,
                "github_path": file.repo_path,
                "size_bytes": file.size_bytes,
                "size": bytes_label(file.size_bytes),
            }
        )
    return buffer.getvalue().encode("utf-8")


def push_log_csv(result: Dict[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(result.keys()))
    writer.writeheader()
    writer.writerow(result)
    return buffer.getvalue().encode("utf-8")


def sidebar_settings() -> Dict[str, Any]:
    st.sidebar.title("GitHub API")
    st.sidebar.caption("Paste a GitHub token here or store it as `GITHUB_TOKEN` in Streamlit secrets.")

    token = st.sidebar.text_input("GitHub token", value=get_secret("GITHUB_TOKEN", ""), type="password")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        owner = st.text_input("Owner", value=get_secret("GITHUB_OWNER", ""), placeholder="your-user-or-org")
    with col2:
        repo = st.text_input("Repo", value=get_secret("GITHUB_REPO", ""), placeholder="my-streamlit-app")

    branch = st.sidebar.text_input("Branch", value=get_secret("GITHUB_BRANCH", "main"))
    target_folder = st.sidebar.text_input("Target folder", value=get_secret("GITHUB_TARGET_FOLDER", ""), help="Leave blank for repo root.")
    api_base = st.sidebar.text_input("API base", value=get_secret("GITHUB_API_BASE", DEFAULT_API_BASE))

    with st.sidebar.expander("Direct upload options", expanded=True):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        commit_message = st.text_input("Commit message", value=f"Upload project from Streamlit - {now}")
        overwrite_existing = st.checkbox("Overwrite matching files", value=True)
        create_branch_if_missing = st.checkbox("Create branch if missing", value=True)
        create_repo_if_missing = st.checkbox("Create repo if missing", value=False)
        new_repo_private = st.checkbox("New repo private", value=True)
        force_ref_update = st.checkbox("Force branch update if GitHub rejects fast-forward", value=False)

    with st.sidebar.expander("ZIP extraction", expanded=False):
        strip_top_folder = st.checkbox("Remove top ZIP folder", value=True)
        flatten_paths = st.checkbox("Flatten all paths", value=False)
        skip_secrets = st.checkbox("Skip secrets / credentials", value=True)
        include_original_zip = st.checkbox("Also upload original ZIP to /archives", value=False)
        max_file_mb = st.number_input("Max file MB", min_value=1, max_value=100, value=50, step=1)
        max_total_mb = st.number_input("Max extracted total MB", min_value=10, max_value=5000, value=500, step=10)
        max_files = st.number_input("Max files", min_value=1, max_value=10000, value=1000, step=50)

    with st.sidebar.expander("Clean/replace mode", expanded=False):
        st.warning("Only use this when you want to replace an existing target folder.")
        clean_target_folder = st.checkbox("Delete old files in target folder before upload", value=False)
        clean_confirmation = st.text_input("Type CLEAN to allow delete", value="", disabled=not clean_target_folder)

    with st.sidebar.expander("Committer", expanded=False):
        committer_name = st.text_input("Committer name", value=get_secret("GITHUB_COMMITTER_NAME", ""))
        committer_email = st.text_input("Committer email", value=get_secret("GITHUB_COMMITTER_EMAIL", ""))

    with st.sidebar.expander("Ignored folders/files", expanded=False):
        ignore_text = st.text_area(
            "One item per line",
            value="\n".join(sorted(DEFAULT_IGNORE_DIRS | DEFAULT_IGNORE_FILES)),
            height=220,
        )

    ignore_dirs, ignore_files = parse_ignore_text(ignore_text)

    return {
        "token": token,
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "target_folder": target_folder,
        "api_base": api_base,
        "commit_message": commit_message,
        "overwrite_existing": overwrite_existing,
        "create_branch_if_missing": create_branch_if_missing,
        "create_repo_if_missing": create_repo_if_missing,
        "new_repo_private": new_repo_private,
        "force_ref_update": force_ref_update,
        "strip_top_folder": strip_top_folder,
        "flatten_paths": flatten_paths,
        "skip_secrets": skip_secrets,
        "include_original_zip": include_original_zip,
        "max_file_mb": int(max_file_mb),
        "max_total_mb": int(max_total_mb),
        "max_files": int(max_files),
        "clean_target_folder": clean_target_folder,
        "clean_confirmation": clean_confirmation,
        "committer_name": committer_name.strip() or None,
        "committer_email": committer_email.strip() or None,
        "ignore_dirs": ignore_dirs,
        "ignore_files": ignore_files,
    }


def validate_settings(settings: Dict[str, Any]) -> None:
    validate_branch(settings["branch"])
    sanitize_folder(settings["target_folder"])
    if settings["clean_target_folder"] and settings["clean_confirmation"].strip().upper() != "CLEAN":
        raise ValueError("Clean/replace mode is on. Type CLEAN in the sidebar before uploading.")


def render_push_result(result: Dict[str, Any]) -> None:
    if result.get("status") == "nothing_to_commit":
        st.warning(result.get("message", "Nothing changed."))
    else:
        st.success("Uploaded to GitHub successfully.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Files uploaded", int(result.get("files_uploaded", 0)))
    c2.metric("Skipped existing", int(result.get("files_skipped_existing", 0)))
    c3.metric("Deleted first", int(result.get("files_deleted_first", 0)))

    commit_url = result.get("commit_url")
    tree_url = result.get("tree_url")
    if commit_url:
        st.link_button("Open GitHub commit", commit_url, use_container_width=False)
    if tree_url:
        st.link_button("Open uploaded files on GitHub", tree_url, use_container_width=False)

    st.download_button(
        "Download GitHub push log CSV",
        data=push_log_csv(result),
        file_name="github_push_log.csv",
        mime="text/csv",
    )


def push_files_now(files: Sequence[RepoFile], settings: Dict[str, Any]) -> Dict[str, Any]:
    validate_settings(settings)
    client = GitHubClient(
        token=settings["token"],
        owner=settings["owner"],
        repo=settings["repo"],
        api_base=settings["api_base"],
    )

    repo_info = client.ensure_repo(
        create_if_missing=settings["create_repo_if_missing"],
        private=settings["new_repo_private"],
        description="Uploaded from Streamlit ZIP to GitHub Direct Pusher",
    )

    progress = st.progress(0, text="Starting GitHub upload…")

    def update_progress(percent: float, text: str) -> None:
        progress.progress(max(0.0, min(float(percent), 1.0)), text=text)

    try:
        result = client.direct_push(
            files=files,
            branch=settings["branch"],
            commit_message=settings["commit_message"],
            repo_info=repo_info,
            overwrite_existing=settings["overwrite_existing"],
            create_branch_if_missing=settings["create_branch_if_missing"],
            clean_target_folder=settings["clean_target_folder"],
            target_folder=settings["target_folder"],
            force_ref_update=settings["force_ref_update"],
            committer_name=settings["committer_name"],
            committer_email=settings["committer_email"],
            progress=update_progress,
        )
        return result
    finally:
        time.sleep(0.2)
        progress.empty()


def direct_zip_page(settings: Dict[str, Any]) -> None:
    st.subheader("Direct ZIP upload")
    st.write("Upload a ZIP, click once, and the extracted project is pushed to GitHub. No code review screen required.")

    zip_file = st.file_uploader("Upload project ZIP", type=["zip"], accept_multiple_files=False)
    if not zip_file:
        st.info("Choose a `.zip` file to send it directly to GitHub.")
        return

    zip_bytes = zip_file.getvalue()
    c1, c2 = st.columns(2)
    c1.metric("ZIP file", zip_file.name)
    c2.metric("ZIP size", bytes_label(len(zip_bytes)))

    button_label = "Upload ZIP to GitHub now"
    if st.button(button_label, type="primary", use_container_width=True):
        try:
            with st.spinner("Opening ZIP and preparing files…"):
                build = build_zip_files(
                    zip_bytes=zip_bytes,
                    zip_name=zip_file.name,
                    target_folder=settings["target_folder"],
                    strip_top_folder=settings["strip_top_folder"],
                    flatten_paths=settings["flatten_paths"],
                    ignore_dirs=settings["ignore_dirs"],
                    ignore_files=settings["ignore_files"],
                    skip_secrets=settings["skip_secrets"],
                    max_file_mb=settings["max_file_mb"],
                    max_total_mb=settings["max_total_mb"],
                    max_files=settings["max_files"],
                    include_original_zip=settings["include_original_zip"],
                )

            if not build.files:
                st.error("No files were uploadable after ZIP filtering.")
                if build.skipped:
                    with st.expander("Skipped files"):
                        st.dataframe([{"File": f, "Reason": r} for f, r in build.skipped], hide_index=True, use_container_width=True)
                return

            st.caption(
                f"Prepared {len(build.files):,} file(s), {bytes_label(sum(f.size_bytes for f in build.files))}. "
                f"Skipped {len(build.skipped):,}."
            )
            result = push_files_now(build.files, settings)
            render_push_result(result)

            with st.expander("Upload summary", expanded=False):
                if build.removed_root:
                    st.write(f"Removed top ZIP folder: `{build.removed_root}/`")
                st.download_button(
                    "Download uploaded file list CSV",
                    data=files_csv(build.files),
                    file_name="github_uploaded_files.csv",
                    mime="text/csv",
                )
                if build.skipped:
                    st.dataframe(
                        [{"Skipped file": f, "Reason": r} for f, r in build.skipped],
                        hide_index=True,
                        use_container_width=True,
                    )
        except Exception as exc:
            st.error(str(exc))


def folder_file_page(settings: Dict[str, Any]) -> None:
    st.subheader("Direct files/folder upload")
    st.write("Use this when you do not have a ZIP. It also uploads directly without code preview.")

    mode = st.radio("Upload type", ["Multiple files", "Folder"], horizontal=True)
    kwargs: Dict[str, Any] = {
        "label": "Choose files" if mode == "Multiple files" else "Choose folder",
        "accept_multiple_files": True if mode == "Multiple files" else "directory",
    }
    uploaded = st.file_uploader(**kwargs)
    if not uploaded:
        st.info("Choose files or a folder to upload.")
        return

    if st.button("Upload selected files to GitHub now", type="primary", use_container_width=True):
        try:
            files = make_files_from_uploads(uploaded, settings["target_folder"], settings["flatten_paths"])
            st.caption(f"Prepared {len(files):,} file(s), {bytes_label(sum(f.size_bytes for f in files))}.")
            result = push_files_now(files, settings)
            render_push_result(result)
            with st.expander("Upload summary", expanded=False):
                st.download_button(
                    "Download uploaded file list CSV",
                    data=files_csv(files),
                    file_name="github_uploaded_files.csv",
                    mime="text/csv",
                )
        except Exception as exc:
            st.error(str(exc))


def connection_page(settings: Dict[str, Any]) -> None:
    st.subheader("Connection check")
    st.write("Use this once to confirm the token can reach the selected repository.")
    if st.button("Test GitHub connection", type="primary"):
        try:
            validate_settings(settings)
            client = GitHubClient(settings["token"], settings["owner"], settings["repo"], settings["api_base"])
            repo = client.ensure_repo(
                create_if_missing=settings["create_repo_if_missing"],
                private=settings["new_repo_private"],
                description="Uploaded from Streamlit ZIP to GitHub Direct Pusher",
            )
            default_branch = repo.get("default_branch", "unknown")
            visibility = "private" if repo.get("private") else "public"
            st.success(f"Connected to {settings['owner']}/{settings['repo']} ({visibility}). Default branch: {default_branch}.")
            st.link_button("Open repository", repo.get("html_url", f"https://github.com/{settings['owner']}/{settings['repo']}"))
        except Exception as exc:
            st.error(str(exc))


def help_page() -> None:
    st.subheader("Setup")
    st.markdown(
        """
### What this app does
This is a direct project uploader. The normal flow is:

1. Put your GitHub token, owner, repo, branch, and target folder in the sidebar.
2. Upload a `.zip` project.
3. Click **Upload ZIP to GitHub now**.
4. The app extracts the ZIP, skips junk/secrets, creates Git blobs, creates one tree, creates one commit, and moves the branch to that commit.

### GitHub token
Use a fine-grained personal access token with access to the repo you want to update. For normal uploading, grant **Contents: Read and write**. To create repositories from the app, the token must also be allowed to create repos for your account or organization.

### Good ZIP structure
Your ZIP can contain a folder like this:

```text
my-app/
  app.py
  requirements.txt
  README.md
  .streamlit/
    config.toml
```

With **Remove top ZIP folder** turned on, it uploads as:

```text
app.py
requirements.txt
README.md
.streamlit/config.toml
```

### Files skipped by default
The app skips `.git`, `node_modules`, virtual environments, Python caches, build folders, `.env`, `.streamlit/secrets.toml`, and common credential-looking files. Keep that on for safer uploads.

### Replace mode
Use **Delete old files in target folder before upload** only when you want the GitHub folder to exactly match the ZIP. It requires typing `CLEAN` in the sidebar.
        """
    )


def main() -> None:
    st.set_page_config(page_title="Direct ZIP → GitHub", page_icon="🚀", layout="wide")

    st.title("🚀 Direct ZIP → GitHub Uploader")
    st.caption(f"Version {APP_VERSION} · one-click ZIP extraction and GitHub commit")
    st.write("No code review step. Upload the ZIP and push the project straight to GitHub from the browser.")

    settings = sidebar_settings()

    tab_zip, tab_files, tab_test, tab_help = st.tabs(["ZIP → GitHub", "Files / Folder", "Test", "Help"])
    with tab_zip:
        direct_zip_page(settings)
    with tab_files:
        folder_file_page(settings)
    with tab_test:
        connection_page(settings)
    with tab_help:
        help_page()


if __name__ == "__main__":
    main()
