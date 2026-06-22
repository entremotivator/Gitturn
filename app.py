"""Direct ZIP -> GitHub Streamlit uploader.

Upload a ZIP, click once, and push the extracted files straight to GitHub.
No file review screen is required.
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

APP_VERSION = "4.0.0"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_API_BASE = "https://api.github.com"
MAX_GITHUB_FILE_BYTES = 100 * 1024 * 1024
SAFE_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")

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
    ".next/cache",
    ".turbo",
    ".parcel-cache",
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

SECRET_FRAGMENTS = [
    ".env",
    "secrets.toml",
    ".streamlit/secrets.toml",
    "private_key",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account",
    "service_account",
    "client_secret",
    "firebase-adminsdk",
]


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
class ZipResult:
    files: List[RepoFile]
    skipped: List[Tuple[str, str]]
    removed_root: str
    entry_count: int
    total_uncompressed: int


@dataclass
class BranchState:
    branch: str
    ref_exists: bool
    empty_repo: bool
    parent_commit_sha: Optional[str]
    base_tree_sha: Optional[str]


class GitHubAPIError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class GitHubClient:
    def __init__(self, *, token: str, owner: str, repo: str, api_base: str = DEFAULT_API_BASE):
        self.token = token.strip()
        self.owner = owner.strip()
        self.repo = repo.strip()
        self.api_base = api_base.rstrip("/")
        if not self.token:
            raise ValueError("Add a GitHub token in the sidebar.")
        if not self.owner:
            raise ValueError("Add the GitHub owner/user/org in the sidebar.")
        if not self.repo:
            raise ValueError("Add the GitHub repo name in the sidebar.")
        if not SAFE_REPO_RE.match(self.repo):
            raise ValueError("Repo name can only contain letters, numbers, dots, dashes, and underscores.")

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
        timeout = kwargs.pop("timeout", 120)
        return requests.request(method, self._url(path), headers=self.headers, timeout=timeout, **kwargs)

    @staticmethod
    def _payload(resp: requests.Response) -> Dict[str, Any]:
        try:
            payload = resp.json()
            return payload if isinstance(payload, dict) else {"message": str(payload)[:1000]}
        except Exception:
            return {"message": resp.text[:1000]}

    def _raise(self, resp: requests.Response, fallback: str) -> None:
        payload = self._payload(resp)
        message = payload.get("message") or fallback
        doc_url = payload.get("documentation_url")
        detail = f" {doc_url}" if doc_url else ""
        raise GitHubAPIError(f"{fallback} GitHub said: {message}.{detail}", resp.status_code, payload)

    def me(self) -> Dict[str, Any]:
        resp = self._request("GET", "/user")
        if resp.status_code >= 400:
            self._raise(resp, "Token test failed.")
        return resp.json()

    def get_repo(self) -> Optional[Dict[str, Any]]:
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            self._raise(resp, "Could not access the repo.")
        return resp.json()

    def ensure_repo(self, *, create_if_missing: bool, new_repo_private: bool) -> Dict[str, Any]:
        repo_info = self.get_repo()
        if repo_info:
            return repo_info
        if not create_if_missing:
            raise GitHubAPIError(
                f"Repo {self.owner}/{self.repo} was not found. Turn on 'Create repo if missing' or create it in GitHub first."
            )

        user = self.me()
        owner_is_user = str(user.get("login", "")).lower() == self.owner.lower()
        body = {
            "name": self.repo,
            "private": bool(new_repo_private),
            "description": "Created by Direct ZIP to GitHub Streamlit Uploader",
            # Important: initialize the repo so GitHub has a default branch for contents uploads.
            "auto_init": True,
        }
        path = "/user/repos" if owner_is_user else f"/orgs/{self.owner}/repos"
        resp = self._request("POST", path, json=body, timeout=180)
        if resp.status_code >= 400:
            self._raise(resp, "Could not create the repo.")
        return resp.json()

    def get_ref(self, branch: str) -> Optional[Dict[str, Any]]:
        encoded = quote(branch, safe="/")
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}/git/ref/heads/{encoded}")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            self._raise(resp, f"Could not read branch '{branch}'.")
        return resp.json()

    def create_ref(self, branch: str, commit_sha: str) -> Dict[str, Any]:
        resp = self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            timeout=180,
        )
        if resp.status_code >= 400:
            self._raise(resp, f"Could not create branch '{branch}'.")
        return resp.json()

    def update_ref(self, branch: str, commit_sha: str, *, force: bool = False) -> Dict[str, Any]:
        encoded = quote(branch, safe="/")
        resp = self._request(
            "PATCH",
            f"/repos/{self.owner}/{self.repo}/git/refs/heads/{encoded}",
            json={"sha": commit_sha, "force": bool(force)},
            timeout=180,
        )
        if resp.status_code >= 400:
            self._raise(resp, f"Could not update branch '{branch}'.")
        return resp.json()

    def get_commit(self, commit_sha: str) -> Dict[str, Any]:
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}/git/commits/{commit_sha}")
        if resp.status_code >= 400:
            self._raise(resp, "Could not read current commit.")
        return resp.json()

    def get_tree(self, tree_sha: str, *, recursive: bool = False) -> Dict[str, Any]:
        params = {"recursive": "1"} if recursive else None
        resp = self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/git/trees/{tree_sha}",
            params=params,
            timeout=180,
        )
        if resp.status_code >= 400:
            self._raise(resp, "Could not read repository tree.")
        return resp.json()

    def get_branch_state(self, branch: str, repo_info: Dict[str, Any], *, create_branch_if_missing: bool) -> BranchState:
        ref = self.get_ref(branch)
        if ref:
            commit_sha = ref.get("object", {}).get("sha")
            commit = self.get_commit(commit_sha)
            tree_sha = commit.get("tree", {}).get("sha")
            return BranchState(branch, True, False, commit_sha, tree_sha)

        default_branch = repo_info.get("default_branch") or "main"
        default_ref = self.get_ref(default_branch)
        if default_ref:
            default_commit_sha = default_ref.get("object", {}).get("sha")
            default_commit = self.get_commit(default_commit_sha)
            default_tree_sha = default_commit.get("tree", {}).get("sha")
            if branch != default_branch and not create_branch_if_missing:
                raise GitHubAPIError(f"Branch '{branch}' does not exist. Turn on 'Create branch if missing'.")
            return BranchState(branch, False, False, default_commit_sha, default_tree_sha)

        # Existing empty repo with no branches.
        return BranchState(branch, False, True, None, None)

    def create_blob(self, content: bytes) -> str:
        resp = self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/git/blobs",
            json={"content": base64.b64encode(content).decode("utf-8"), "encoding": "base64"},
            timeout=180,
        )
        if resp.status_code >= 400:
            self._raise(resp, "Could not upload file blob.")
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
            self._raise(resp, "Could not create Git tree.")
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
            self._raise(resp, "Could not create Git commit.")
        payload = resp.json()
        if not payload.get("sha"):
            raise GitHubAPIError("GitHub did not return a commit SHA.")
        return payload

    def content_sha(self, path: str, branch: str) -> Optional[str]:
        encoded_path = quote(path, safe="/")
        resp = self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/contents/{encoded_path}",
            params={"ref": branch},
            timeout=120,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            self._raise(resp, f"Could not check existing file: {path}")
        payload = resp.json()
        if isinstance(payload, list):
            raise GitHubAPIError(f"A folder already exists at this file path: {path}")
        return payload.get("sha")

    def put_content(
        self,
        *,
        path: str,
        content: bytes,
        branch: str,
        message: str,
        sha: Optional[str],
        committer_name: Optional[str],
        committer_email: Optional[str],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content).decode("utf-8"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        if committer_name and committer_email:
            person = {"name": committer_name, "email": committer_email}
            body["author"] = person
            body["committer"] = person
        encoded_path = quote(path, safe="/")
        resp = self._request(
            "PUT",
            f"/repos/{self.owner}/{self.repo}/contents/{encoded_path}",
            json=body,
            timeout=180,
        )
        if resp.status_code >= 400:
            self._raise(resp, f"Could not upload file: {path}")
        return resp.json()

    def direct_upload_contents_api(
        self,
        *,
        files: Sequence[RepoFile],
        branch: str,
        commit_message: str,
        repo_info: Dict[str, Any],
        overwrite_existing: bool,
        create_branch_if_missing: bool,
        committer_name: Optional[str],
        committer_email: Optional[str],
        progress: Callable[[float, str], None],
    ) -> Dict[str, Any]:
        state = self.get_branch_state(branch, repo_info, create_branch_if_missing=create_branch_if_missing)
        if state.empty_repo:
            return self.direct_upload_single_commit(
                files=files,
                branch=branch,
                commit_message=commit_message,
                repo_info=repo_info,
                overwrite_existing=overwrite_existing,
                create_branch_if_missing=create_branch_if_missing,
                clean_target_folder=False,
                target_folder="",
                force_update=False,
                committer_name=committer_name,
                committer_email=committer_email,
                progress=progress,
            )

        if not state.ref_exists:
            progress(0.03, f"Creating branch '{branch}' from the repo default branch…")
            self.create_ref(branch, state.parent_commit_sha)  # type: ignore[arg-type]

        uploaded = 0
        skipped_existing = 0
        latest_commit = ""
        total = len(files)
        for index, file in enumerate(files, start=1):
            if file.size_bytes > MAX_GITHUB_FILE_BYTES:
                raise GitHubAPIError(f"GitHub rejects files over 100 MB: {file.repo_path}")
            progress(index / max(total, 1), f"Uploading {index}/{total}: {file.repo_path}")
            sha = self.content_sha(file.repo_path, branch)
            if sha and not overwrite_existing:
                skipped_existing += 1
                continue
            result = self.put_content(
                path=file.repo_path,
                content=file.content,
                branch=branch,
                message=commit_message,
                sha=sha,
                committer_name=committer_name,
                committer_email=committer_email,
            )
            uploaded += 1
            latest_commit = result.get("commit", {}).get("sha", latest_commit)

        return {
            "status": "committed" if uploaded else "nothing_to_commit",
            "engine": "compatibility_contents_api",
            "files_uploaded": uploaded,
            "files_skipped_existing": skipped_existing,
            "files_deleted_first": 0,
            "commit_sha": latest_commit,
            "commit_url": f"https://github.com/{self.owner}/{self.repo}/commit/{latest_commit}" if latest_commit else "",
        }

    def direct_upload_single_commit(
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
        force_update: bool,
        committer_name: Optional[str],
        committer_email: Optional[str],
        progress: Callable[[float, str], None],
    ) -> Dict[str, Any]:
        state = self.get_branch_state(branch, repo_info, create_branch_if_missing=create_branch_if_missing)
        existing_paths: set[str] = set()
        if state.base_tree_sha:
            progress(0.03, "Reading existing GitHub tree…")
            tree = self.get_tree(state.base_tree_sha, recursive=True)
            existing_paths = {
                item.get("path", "")
                for item in tree.get("tree", [])
                if item.get("type") == "blob" and item.get("path")
            }

        upload_files: List[RepoFile] = []
        skipped_existing = 0
        for file in files:
            if file.repo_path in existing_paths and not overwrite_existing and not clean_target_folder:
                skipped_existing += 1
            else:
                upload_files.append(file)

        upload_paths = {file.repo_path for file in upload_files}
        delete_items: List[Dict[str, Any]] = []
        if clean_target_folder and state.base_tree_sha:
            folder = sanitize_folder(target_folder)
            if folder:
                candidates = [p for p in existing_paths if p == folder or p.startswith(folder + "/")]
            else:
                candidates = list(existing_paths)
            delete_items = [
                {"path": path, "mode": "100644", "type": "blob", "sha": None}
                for path in sorted(candidates)
                if path not in upload_paths
            ]

        if not upload_files and not delete_items:
            return {
                "status": "nothing_to_commit",
                "engine": "single_commit_git_database_api",
                "files_uploaded": 0,
                "files_skipped_existing": skipped_existing,
                "files_deleted_first": 0,
                "commit_sha": "",
                "commit_url": "",
            }

        tree_items: List[Dict[str, Any]] = list(delete_items)
        total = len(upload_files)
        for index, file in enumerate(upload_files, start=1):
            if file.size_bytes > MAX_GITHUB_FILE_BYTES:
                raise GitHubAPIError(f"GitHub rejects files over 100 MB: {file.repo_path}")
            progress(0.05 + (index / max(total, 1)) * 0.75, f"Creating Git blob {index}/{total}: {file.repo_path}")
            blob_sha = self.create_blob(file.content)
            tree_items.append({"path": file.repo_path, "mode": "100644", "type": "blob", "sha": blob_sha})

        progress(0.84, "Creating Git tree…")
        tree_sha = self.create_tree(tree_items, base_tree_sha=state.base_tree_sha)
        progress(0.92, "Creating Git commit…")
        commit = self.create_commit(
            message=commit_message,
            tree_sha=tree_sha,
            parent_sha=state.parent_commit_sha,
            committer_name=committer_name,
            committer_email=committer_email,
        )
        commit_sha = commit["sha"]
        progress(0.97, "Updating branch ref…")
        if state.ref_exists:
            self.update_ref(branch, commit_sha, force=force_update)
        else:
            self.create_ref(branch, commit_sha)

        return {
            "status": "committed",
            "engine": "single_commit_git_database_api",
            "files_uploaded": len(upload_files),
            "files_skipped_existing": skipped_existing,
            "files_deleted_first": len(delete_items),
            "commit_sha": commit_sha,
            "commit_url": f"https://github.com/{self.owner}/{self.repo}/commit/{commit_sha}",
        }


# ---------- path and ZIP utilities ----------


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)  # type: ignore[attr-defined]
        return str(value) if value is not None else default
    except Exception:
        return default


def bytes_label(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def sanitize_folder(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip().strip("/")
    if not value:
        return ""
    normalized = posixpath.normpath(value).replace("\\", "/")
    if normalized in (".", ""):
        return ""
    if normalized.startswith("../") or normalized == ".." or "/../" in normalized or normalized.startswith("/"):
        raise ValueError(f"Unsafe folder path rejected: {value}")
    return normalized


def safe_repo_path(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip().strip("/")
    normalized = posixpath.normpath(value).replace("\\", "/")
    if normalized in (".", ""):
        raise ValueError("File path cannot be empty.")
    if normalized.startswith("../") or normalized == ".." or "/../" in normalized or normalized.startswith("/"):
        raise ValueError(f"Unsafe file path rejected: {value}")
    return normalized


def combine_repo_path(target_folder: str, relative_path: str, *, flatten_paths: bool = False) -> str:
    relative_path = str(relative_path or "").replace("\\", "/").strip("/")
    if flatten_paths:
        relative_path = relative_path.split("/")[-1]
    folder = sanitize_folder(target_folder)
    return safe_repo_path(f"{folder}/{relative_path}" if folder else relative_path)


def quote_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in path.split("/"))


def repo_tree_url(owner: str, repo: str, branch: str, target_folder: str) -> str:
    branch_part = quote(branch, safe="/")
    folder = sanitize_folder(target_folder)
    if folder:
        return f"https://github.com/{owner}/{repo}/tree/{branch_part}/{quote_path(folder)}"
    return f"https://github.com/{owner}/{repo}/tree/{branch_part}"


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    file_type = (info.external_attr >> 16) & 0o170000
    return file_type == 0o120000


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


def should_skip(path: str, ignore_dirs: set[str], ignore_files: set[str], skip_secrets: bool) -> Tuple[bool, str]:
    clean = path.replace("\\", "/").strip("/")
    if not clean:
        return True, "empty path"
    parts = clean.split("/")
    filename = parts[-1]
    if filename in ignore_files or clean in ignore_files:
        return True, "ignored file"
    if filename.endswith((".pyc", ".pyo")):
        return True, "compiled Python cache"
    for part in parts:
        if part in ignore_dirs:
            return True, f"ignored folder: {part}"
    if skip_secrets:
        lowered = clean.lower()
        if any(fragment in lowered for fragment in SECRET_FRAGMENTS):
            return True, "secret/credential-looking file"
    return False, ""


def common_top_folder(paths: Sequence[str]) -> str:
    if not paths:
        return ""
    first = paths[0].split("/")[0]
    if not first:
        return ""
    if all(path.startswith(first + "/") for path in paths) and any("/" in path for path in paths):
        return first
    return ""


def strip_root(path: str, root: str) -> str:
    if root and path.startswith(root + "/"):
        return path[len(root) + 1 :]
    return path


def extract_zip_to_files(
    *,
    zip_bytes: bytes,
    zip_name: str,
    target_folder: str,
    strip_top_folder: bool,
    flatten_paths: bool,
    skip_secrets: bool,
    ignore_dirs: set[str],
    ignore_files: set[str],
    max_file_mb: int,
    max_total_mb: int,
    max_files: int,
) -> ZipResult:
    files: List[RepoFile] = []
    skipped: List[Tuple[str, str]] = []
    max_file_bytes = int(max_file_mb) * 1024 * 1024
    max_total_bytes = int(max_total_mb) * 1024 * 1024

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("This file is not a valid ZIP archive.")

    with zf:
        bad_member = zf.testzip()
        if bad_member:
            raise ValueError(f"ZIP appears corrupted around: {bad_member}")

        infos = zf.infolist()
        valid_paths: List[str] = []
        total_uncompressed = 0

        for info in infos:
            raw = info.filename.replace("\\", "/").strip("/")
            if not raw or info.is_dir():
                continue
            if is_zip_symlink(info):
                skipped.append((raw, "symbolic link skipped"))
                continue
            ignored, reason = should_skip(raw, ignore_dirs, ignore_files, skip_secrets)
            if ignored:
                skipped.append((raw, reason))
                continue
            try:
                safe_repo_path(raw)
            except Exception as exc:
                skipped.append((raw, str(exc)))
                continue
            if info.file_size > max_file_bytes:
                skipped.append((raw, f"larger than {max_file_mb} MB limit"))
                continue
            if info.file_size > MAX_GITHUB_FILE_BYTES:
                skipped.append((raw, "GitHub API file limit is 100 MB"))
                continue
            valid_paths.append(raw)
            total_uncompressed += int(info.file_size)

        if len(valid_paths) > int(max_files):
            raise ValueError(f"ZIP has {len(valid_paths):,} uploadable files. Increase Max files or remove files from the ZIP.")
        if total_uncompressed > max_total_bytes:
            raise ValueError(
                f"ZIP expands to {bytes_label(total_uncompressed)}, over the {max_total_mb} MB safety limit."
            )

        root = common_top_folder(valid_paths) if strip_top_folder else ""
        seen: set[str] = set()
        valid_set = set(valid_paths)
        for info in infos:
            raw = info.filename.replace("\\", "/").strip("/")
            if not raw or info.is_dir() or raw not in valid_set:
                continue
            rel = strip_root(raw, root)
            if not rel:
                skipped.append((raw, "top folder only"))
                continue
            content = zf.read(info)
            repo_path = combine_repo_path(target_folder, rel, flatten_paths=flatten_paths)
            if repo_path in seen:
                base, ext = os.path.splitext(repo_path)
                repo_path = f"{base}-{len(seen) + 1}{ext}"
            seen.add(repo_path)
            files.append(RepoFile(archive_path=raw, repo_path=repo_path, content=content, source=zip_name))

    return ZipResult(files, skipped, root, len(infos), total_uncompressed)


def uploaded_files_to_repo_files(uploaded: Iterable[Any], target_folder: str, flatten_paths: bool) -> List[RepoFile]:
    files: List[RepoFile] = []
    seen: set[str] = set()
    for item in uploaded:
        content = item.getvalue()
        repo_path = combine_repo_path(target_folder, item.name, flatten_paths=flatten_paths)
        if len(content) > MAX_GITHUB_FILE_BYTES:
            raise ValueError(f"GitHub rejects files over 100 MB: {item.name}")
        if repo_path in seen:
            base, ext = os.path.splitext(repo_path)
            repo_path = f"{base}-{len(seen) + 1}{ext}"
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


def result_csv(result: Dict[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(result.keys()))
    writer.writeheader()
    writer.writerow(result)
    return buffer.getvalue().encode("utf-8")


# ---------- Streamlit UI ----------


def sidebar() -> Dict[str, Any]:
    st.sidebar.title("GitHub API")
    st.sidebar.caption("Token stays in your running app. Use Streamlit secrets for deployment.")

    token = st.sidebar.text_input("GitHub token", value=get_secret("GITHUB_TOKEN", ""), type="password")
    owner = st.sidebar.text_input("Owner / org", value=get_secret("GITHUB_OWNER", ""), placeholder="your-github-user")
    repo = st.sidebar.text_input("Repository", value=get_secret("GITHUB_REPO", ""), placeholder="my-streamlit-app")
    branch = st.sidebar.text_input("Branch", value=get_secret("GITHUB_BRANCH", "main"))
    target_folder = st.sidebar.text_input("Target folder", value=get_secret("GITHUB_TARGET_FOLDER", ""), help="Blank = repo root")
    api_base = st.sidebar.text_input("API base URL", value=get_secret("GITHUB_API_BASE", DEFAULT_API_BASE))

    with st.sidebar.expander("Upload behavior", expanded=True):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        commit_message = st.text_input("Commit message", value=f"Direct ZIP upload - {now}")
        engine = st.radio(
            "Upload engine",
            ["Compatibility mode - most reliable", "Single commit mode - faster"],
            index=0,
            help="Compatibility uses GitHub Contents API. Single commit uses Git Database API.",
        )
        overwrite_existing = st.checkbox("Overwrite matching files", value=True)
        create_repo_if_missing = st.checkbox("Create repo if missing", value=False)
        create_branch_if_missing = st.checkbox("Create branch if missing", value=True)
        new_repo_private = st.checkbox("New repo private", value=True)

    with st.sidebar.expander("ZIP cleanup", expanded=True):
        strip_top_folder = st.checkbox("Remove top ZIP folder", value=True)
        flatten_paths = st.checkbox("Flatten paths", value=False)
        skip_secrets = st.checkbox("Skip secrets / credentials", value=True)
        max_file_mb = st.number_input("Max single file MB", 1, 100, 50, 1)
        max_total_mb = st.number_input("Max extracted total MB", 10, 5000, 500, 10)
        max_files = st.number_input("Max files", 1, 20000, 3000, 50)

    with st.sidebar.expander("Clean replace mode", expanded=False):
        st.caption("Only works with Single commit mode. It deletes old files in the target folder before upload.")
        clean_target_folder = st.checkbox("Delete old target folder files first", value=False)
        clean_confirmation = st.text_input("Type CLEAN", value="", disabled=not clean_target_folder)
        force_update = st.checkbox("Force branch update", value=False)

    with st.sidebar.expander("Committer", expanded=False):
        committer_name = st.text_input("Committer name", value=get_secret("GITHUB_COMMITTER_NAME", ""))
        committer_email = st.text_input("Committer email", value=get_secret("GITHUB_COMMITTER_EMAIL", ""))

    with st.sidebar.expander("Ignore list", expanded=False):
        ignore_text = st.text_area("Ignored folders/files", value="\n".join(sorted(DEFAULT_IGNORE_DIRS | DEFAULT_IGNORE_FILES)), height=220)

    ignore_dirs, ignore_files = parse_ignore_text(ignore_text)
    return {
        "token": token,
        "owner": owner,
        "repo": repo,
        "branch": branch.strip(),
        "target_folder": target_folder,
        "api_base": api_base,
        "commit_message": commit_message,
        "engine": engine,
        "overwrite_existing": overwrite_existing,
        "create_repo_if_missing": create_repo_if_missing,
        "create_branch_if_missing": create_branch_if_missing,
        "new_repo_private": new_repo_private,
        "strip_top_folder": strip_top_folder,
        "flatten_paths": flatten_paths,
        "skip_secrets": skip_secrets,
        "max_file_mb": int(max_file_mb),
        "max_total_mb": int(max_total_mb),
        "max_files": int(max_files),
        "clean_target_folder": clean_target_folder,
        "clean_confirmation": clean_confirmation,
        "force_update": force_update,
        "committer_name": committer_name.strip() or None,
        "committer_email": committer_email.strip() or None,
        "ignore_dirs": ignore_dirs,
        "ignore_files": ignore_files,
    }


def validate_settings(settings: Dict[str, Any]) -> None:
    if not settings["branch"] or not SAFE_BRANCH_RE.match(settings["branch"]):
        raise ValueError("Branch name looks invalid.")
    sanitize_folder(settings["target_folder"])
    if settings["clean_target_folder"]:
        if settings["engine"].startswith("Compatibility"):
            raise ValueError("Clean replace mode needs 'Single commit mode - faster'.")
        if settings["clean_confirmation"].strip().upper() != "CLEAN":
            raise ValueError("Type CLEAN in the sidebar to use clean replace mode.")


def make_client(settings: Dict[str, Any]) -> GitHubClient:
    validate_settings(settings)
    return GitHubClient(
        token=settings["token"],
        owner=settings["owner"],
        repo=settings["repo"],
        api_base=settings["api_base"],
    )


def direct_push(files: Sequence[RepoFile], settings: Dict[str, Any]) -> Dict[str, Any]:
    if not files:
        raise ValueError("No files available to upload after filtering.")
    client = make_client(settings)
    repo_info = client.ensure_repo(
        create_if_missing=settings["create_repo_if_missing"],
        new_repo_private=settings["new_repo_private"],
    )

    progress = st.progress(0, text="Starting GitHub upload…")

    def update(percent: float, text: str) -> None:
        progress.progress(max(0.0, min(float(percent), 1.0)), text=text)

    try:
        if settings["engine"].startswith("Compatibility"):
            result = client.direct_upload_contents_api(
                files=files,
                branch=settings["branch"],
                commit_message=settings["commit_message"],
                repo_info=repo_info,
                overwrite_existing=settings["overwrite_existing"],
                create_branch_if_missing=settings["create_branch_if_missing"],
                committer_name=settings["committer_name"],
                committer_email=settings["committer_email"],
                progress=update,
            )
        else:
            result = client.direct_upload_single_commit(
                files=files,
                branch=settings["branch"],
                commit_message=settings["commit_message"],
                repo_info=repo_info,
                overwrite_existing=settings["overwrite_existing"],
                create_branch_if_missing=settings["create_branch_if_missing"],
                clean_target_folder=settings["clean_target_folder"],
                target_folder=settings["target_folder"],
                force_update=settings["force_update"],
                committer_name=settings["committer_name"],
                committer_email=settings["committer_email"],
                progress=update,
            )
        result["repo"] = f"{settings['owner']}/{settings['repo']}"
        result["branch"] = settings["branch"]
        result["target_folder"] = sanitize_folder(settings["target_folder"])
        result["tree_url"] = repo_tree_url(settings["owner"], settings["repo"], settings["branch"], settings["target_folder"])
        return result
    finally:
        time.sleep(0.25)
        progress.empty()


def show_result(result: Dict[str, Any], files: Sequence[RepoFile], skipped: Optional[Sequence[Tuple[str, str]]] = None, removed_root: str = "") -> None:
    if result.get("status") == "nothing_to_commit":
        st.warning("Nothing changed. Existing files were skipped because overwrite is off.")
    else:
        st.success("Direct upload complete.")

    a, b, c, d = st.columns(4)
    a.metric("Uploaded", int(result.get("files_uploaded", 0)))
    b.metric("Skipped existing", int(result.get("files_skipped_existing", 0)))
    c.metric("Deleted first", int(result.get("files_deleted_first", 0)))
    d.metric("Engine", "Compat" if "contents" in result.get("engine", "") else "Single")

    if result.get("commit_url"):
        st.link_button("Open GitHub commit", result["commit_url"])
    if result.get("tree_url"):
        st.link_button("Open uploaded files", result["tree_url"])

    st.download_button("Download upload log CSV", data=result_csv(result), file_name="github_upload_log.csv", mime="text/csv")
    st.download_button("Download uploaded file list CSV", data=files_csv(files), file_name="github_uploaded_files.csv", mime="text/csv")

    with st.expander("Upload details", expanded=False):
        if removed_root:
            st.write(f"Removed top ZIP folder: `{removed_root}/`")
        st.write(f"Prepared {len(files):,} file(s), {bytes_label(sum(f.size_bytes for f in files))}.")
        if skipped:
            st.write(f"Skipped {len(skipped):,} file(s).")
            st.dataframe([{"file": f, "reason": r} for f, r in skipped], hide_index=True, use_container_width=True)


def direct_zip_tab(settings: Dict[str, Any]) -> None:
    st.header("Direct ZIP upload")
    st.caption("Upload a ZIP and click one button. The app opens it, filters junk/secrets, and pushes files to GitHub immediately.")

    uploaded_zip = st.file_uploader("Choose project ZIP", type=["zip"], accept_multiple_files=False)
    if not uploaded_zip:
        st.info("Choose a `.zip` file to start.")
        return

    zip_bytes = uploaded_zip.getvalue()
    col1, col2, col3 = st.columns(3)
    col1.metric("ZIP name", uploaded_zip.name)
    col2.metric("ZIP size", bytes_label(len(zip_bytes)))
    col3.metric("Destination", f"{settings['owner'] or 'owner'}/{settings['repo'] or 'repo'}")

    if st.button("Upload ZIP directly to GitHub", type="primary", use_container_width=True):
        try:
            with st.spinner("Opening ZIP and preparing direct upload…"):
                build = extract_zip_to_files(
                    zip_bytes=zip_bytes,
                    zip_name=uploaded_zip.name,
                    target_folder=settings["target_folder"],
                    strip_top_folder=settings["strip_top_folder"],
                    flatten_paths=settings["flatten_paths"],
                    skip_secrets=settings["skip_secrets"],
                    ignore_dirs=settings["ignore_dirs"],
                    ignore_files=settings["ignore_files"],
                    max_file_mb=settings["max_file_mb"],
                    max_total_mb=settings["max_total_mb"],
                    max_files=settings["max_files"],
                )
            if not build.files:
                st.error("No uploadable files were found inside the ZIP after filtering.")
                if build.skipped:
                    st.dataframe([{"file": f, "reason": r} for f, r in build.skipped], hide_index=True, use_container_width=True)
                return
            result = direct_push(build.files, settings)
            show_result(result, build.files, build.skipped, build.removed_root)
        except Exception as exc:
            st.error(str(exc))
            with st.expander("What to check"):
                st.markdown(
                    """
- Make sure the GitHub token has **Contents: Read and write** permission for the repo.
- Turn on **Create repo if missing** if the repo does not exist.
- If your repo is empty or brand new, leave **Create branch if missing** on.
- If the target folder already has files, keep **Overwrite matching files** on.
- Try **Compatibility mode - most reliable** first.
                    """
                )


def files_tab(settings: Dict[str, Any]) -> None:
    st.header("Direct file/folder upload")
    mode = st.radio("Upload type", ["Multiple files", "Folder"], horizontal=True)
    uploaded = st.file_uploader(
        "Choose files" if mode == "Multiple files" else "Choose folder",
        accept_multiple_files=True if mode == "Multiple files" else "directory",
    )
    if not uploaded:
        st.info("Choose files or a folder.")
        return
    if st.button("Upload selected files directly to GitHub", type="primary", use_container_width=True):
        try:
            files = uploaded_files_to_repo_files(uploaded, settings["target_folder"], settings["flatten_paths"])
            result = direct_push(files, settings)
            show_result(result, files)
        except Exception as exc:
            st.error(str(exc))


def connection_tab(settings: Dict[str, Any]) -> None:
    st.header("Connection check")
    st.write("Use this to test token, repo, and branch access before uploading.")
    if st.button("Test GitHub connection", type="primary"):
        try:
            client = make_client(settings)
            user = client.me()
            repo_info = client.ensure_repo(
                create_if_missing=settings["create_repo_if_missing"],
                new_repo_private=settings["new_repo_private"],
            )
            state = client.get_branch_state(
                settings["branch"],
                repo_info,
                create_branch_if_missing=settings["create_branch_if_missing"],
            )
            visibility = "private" if repo_info.get("private") else "public"
            branch_status = "exists" if state.ref_exists else "will be created / initialized"
            st.success(
                f"Connected as {user.get('login')}. Repo {settings['owner']}/{settings['repo']} is {visibility}. Branch {settings['branch']} {branch_status}."
            )
            st.link_button("Open repo", repo_info.get("html_url", f"https://github.com/{settings['owner']}/{settings['repo']}"))
        except Exception as exc:
            st.error(str(exc))


def help_tab() -> None:
    st.header("How to use")
    st.markdown(
        """
### Fast workflow
1. Put your GitHub token, owner, repo, branch, and target folder in the sidebar.
2. Upload a `.zip` file.
3. Click **Upload ZIP directly to GitHub**.

### Token permissions
For an existing repo, your fine-grained GitHub token needs:

- Repository access to the target repo
- **Contents: Read and write**

To create a repo from the app, the token also needs permission to create repositories for your user or organization.

### Upload engines
- **Compatibility mode - most reliable**: uploads through GitHub's repository contents endpoint. Best for fixing failed uploads and empty/new repos.
- **Single commit mode - faster**: creates Git blobs, one Git tree, one commit, then updates the branch. Best for larger projects when you want one clean commit.

### Safe defaults
The app skips `.git`, `node_modules`, virtual environments, Python cache files, `.env`, `.streamlit/secrets.toml`, and common credential-looking files.
        """
    )


def main() -> None:
    st.set_page_config(page_title="Direct ZIP to GitHub", page_icon="⬆️", layout="wide")
    settings = sidebar()
    st.title("Direct ZIP → GitHub Uploader")
    st.caption(f"Version {APP_VERSION} · Direct upload, no code-review step")

    tab_zip, tab_files, tab_connection, tab_help = st.tabs(["Direct ZIP", "Files / Folder", "Connection", "Help"])
    with tab_zip:
        direct_zip_tab(settings)
    with tab_files:
        files_tab(settings)
    with tab_connection:
        connection_tab(settings)
    with tab_help:
        help_tab()


if __name__ == "__main__":
    main()
