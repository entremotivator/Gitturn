"""Streamlit GitHub ZIP + File Uploader

Upload a ZIP project, open/preview the contents, and commit the extracted files
into a GitHub repository. Also supports regular multi-file and folder upload.
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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests
import streamlit as st


GITHUB_API_VERSION = "2022-11-28"
DEFAULT_API_BASE = "https://api.github.com"
SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")
MAX_GITHUB_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_FILE_MB = 25
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".streamlit/secrets.toml",
}
DEFAULT_IGNORE_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
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
    ".env.example",
    ".gitignore",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
}


@dataclass
class UploadPlanItem:
    display_name: str
    repo_path: str
    size_bytes: int
    content: bytes
    source: str = "file"


@dataclass
class ZipOpenResult:
    plan: List[UploadPlanItem]
    skipped: List[Tuple[str, str]]
    common_root: str
    total_entries: int


class GitHubAPIError(RuntimeError):
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
            raise ValueError("GitHub token is required.")
        if not self.owner:
            raise ValueError("Repository owner is required.")
        if not self.repo:
            raise ValueError("Repository name is required.")

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
        timeout = kwargs.pop("timeout", 60)
        return requests.request(method, self._url(path), headers=self.headers, timeout=timeout, **kwargs)

    def check_repo(self) -> Dict[str, Any]:
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}")
        if resp.status_code >= 400:
            self._raise_api_error(resp, "Could not access repository. Check token, owner, repo, and permissions.")
        return resp.json()

    def get_file_sha(self, repo_path: str, branch: str) -> Optional[str]:
        encoded_path = quote_path(repo_path)
        resp = self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/contents/{encoded_path}",
            params={"ref": branch},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            self._raise_api_error(resp, f"Could not check existing file: {repo_path}")
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("type") == "file":
            return payload.get("sha")
        raise GitHubAPIError(f"Target path exists but is not a file: {repo_path}", resp.status_code, payload)

    def create_or_update_file(
        self,
        *,
        repo_path: str,
        content: bytes,
        branch: str,
        message: str,
        overwrite: bool,
        committer_name: Optional[str] = None,
        committer_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing_sha = self.get_file_sha(repo_path, branch)
        if existing_sha and not overwrite:
            return {
                "status": "skipped",
                "path": repo_path,
                "message": "File already exists and overwrite is off.",
                "html_url": "",
                "commit_url": "",
            }

        encoded_path = quote_path(repo_path)
        body: Dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content).decode("utf-8"),
            "branch": branch,
        }
        if existing_sha:
            body["sha"] = existing_sha
        if committer_name and committer_email:
            body["committer"] = {"name": committer_name, "email": committer_email}

        resp = self._request(
            "PUT",
            f"/repos/{self.owner}/{self.repo}/contents/{encoded_path}",
            json=body,
            timeout=120,
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp, f"Upload failed: {repo_path}")
        payload = resp.json()
        return {
            "status": "updated" if existing_sha else "created",
            "path": repo_path,
            "message": payload.get("commit", {}).get("message", message),
            "html_url": payload.get("content", {}).get("html_url", ""),
            "commit_url": payload.get("commit", {}).get("html_url", ""),
        }

    def get_branch_head(self, branch: str) -> Dict[str, str]:
        encoded_branch = quote(branch, safe="/")
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}/git/ref/heads/{encoded_branch}")
        if resp.status_code >= 400:
            self._raise_api_error(resp, f"Could not read branch ref: {branch}")
        ref_payload = resp.json()
        commit_sha = ref_payload.get("object", {}).get("sha")
        if not commit_sha:
            raise GitHubAPIError(f"Could not find latest commit for branch: {branch}")

        commit_resp = self._request("GET", f"/repos/{self.owner}/{self.repo}/git/commits/{commit_sha}")
        if commit_resp.status_code >= 400:
            self._raise_api_error(commit_resp, f"Could not read branch commit: {branch}")
        commit_payload = commit_resp.json()
        tree_sha = commit_payload.get("tree", {}).get("sha")
        if not tree_sha:
            raise GitHubAPIError(f"Could not find tree for branch: {branch}")
        return {"commit_sha": commit_sha, "tree_sha": tree_sha}

    def create_blob(self, content: bytes) -> str:
        body = {"content": base64.b64encode(content).decode("utf-8"), "encoding": "base64"}
        resp = self._request("POST", f"/repos/{self.owner}/{self.repo}/git/blobs", json=body, timeout=120)
        if resp.status_code >= 400:
            self._raise_api_error(resp, "Could not create Git blob.")
        sha = resp.json().get("sha")
        if not sha:
            raise GitHubAPIError("GitHub did not return a blob SHA.")
        return sha

    def create_tree(self, base_tree_sha: str, tree_items: List[Dict[str, str]]) -> str:
        body = {"base_tree": base_tree_sha, "tree": tree_items}
        resp = self._request("POST", f"/repos/{self.owner}/{self.repo}/git/trees", json=body, timeout=120)
        if resp.status_code >= 400:
            self._raise_api_error(resp, "Could not create Git tree.")
        sha = resp.json().get("sha")
        if not sha:
            raise GitHubAPIError("GitHub did not return a tree SHA.")
        return sha

    def create_commit(
        self,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
        committer_name: Optional[str] = None,
        committer_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"message": message, "tree": tree_sha, "parents": [parent_sha]}
        if committer_name and committer_email:
            committer = {"name": committer_name, "email": committer_email}
            body["committer"] = committer
            body["author"] = committer
        resp = self._request("POST", f"/repos/{self.owner}/{self.repo}/git/commits", json=body, timeout=120)
        if resp.status_code >= 400:
            self._raise_api_error(resp, "Could not create Git commit.")
        payload = resp.json()
        if not payload.get("sha"):
            raise GitHubAPIError("GitHub did not return a commit SHA.")
        return payload

    def update_branch_ref(self, branch: str, commit_sha: str, force: bool = False) -> Dict[str, Any]:
        encoded_branch = quote(branch, safe="/")
        body = {"sha": commit_sha, "force": force}
        resp = self._request("PATCH", f"/repos/{self.owner}/{self.repo}/git/refs/heads/{encoded_branch}", json=body, timeout=120)
        if resp.status_code >= 400:
            self._raise_api_error(resp, f"Could not update branch ref: {branch}")
        return resp.json()

    def commit_many_files(
        self,
        *,
        items: Sequence[UploadPlanItem],
        branch: str,
        message: str,
        committer_name: Optional[str] = None,
        committer_email: Optional[str] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        branch_state = self.get_branch_head(branch)
        tree_items: List[Dict[str, str]] = []
        total = len(items)

        for idx, item in enumerate(items, start=1):
            if item.size_bytes > MAX_GITHUB_FILE_BYTES:
                raise GitHubAPIError(f"GitHub rejects files larger than 100 MB: {item.repo_path}")
            if progress_callback:
                progress_callback(idx, total, f"Creating blob {idx}/{total}: {item.repo_path}")
            blob_sha = self.create_blob(item.content)
            tree_items.append({"path": item.repo_path, "mode": "100644", "type": "blob", "sha": blob_sha})

        if progress_callback:
            progress_callback(total, total, "Creating tree…")
        new_tree_sha = self.create_tree(branch_state["tree_sha"], tree_items)

        if progress_callback:
            progress_callback(total, total, "Creating commit…")
        commit_payload = self.create_commit(
            message=message,
            tree_sha=new_tree_sha,
            parent_sha=branch_state["commit_sha"],
            committer_name=committer_name,
            committer_email=committer_email,
        )

        if progress_callback:
            progress_callback(total, total, "Updating branch…")
        self.update_branch_ref(branch, commit_payload["sha"], force=False)

        commit_url = f"https://github.com/{self.owner}/{self.repo}/commit/{commit_payload['sha']}"
        return {
            "status": "committed",
            "files": len(items),
            "commit_sha": commit_payload["sha"],
            "commit_url": commit_url,
            "message": message,
        }

    @staticmethod
    def _raise_api_error(resp: requests.Response, fallback: str) -> None:
        try:
            payload = resp.json()
        except Exception:
            payload = {"message": resp.text[:800]}
        api_message = payload.get("message") or fallback
        raise GitHubAPIError(f"{fallback} GitHub said: {api_message}", resp.status_code, payload)


def quote_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in path.split("/"))


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)  # type: ignore[attr-defined]
        return str(value) if value is not None else default
    except Exception:
        return default


def sanitize_segment(segment: str) -> str:
    segment = str(segment or "").strip().replace("\\", "/")
    return segment.strip("/")


def safe_norm_path(path: str) -> str:
    path = str(path or "").replace("\\", "/").strip("/")
    normalized = posixpath.normpath(path).replace("\\", "/")
    if normalized in (".", ""):
        raise ValueError("Upload path cannot be empty.")
    if normalized.startswith("../") or normalized == ".." or "/../" in normalized:
        raise ValueError(f"Unsafe path rejected: {path}")
    if normalized.startswith("/"):
        raise ValueError(f"Unsafe absolute path rejected: {path}")
    return normalized


def normalize_repo_path(target_folder: str, uploaded_name: str, flatten: bool = False) -> str:
    target_folder = sanitize_segment(target_folder)
    uploaded_name = str(uploaded_name or "").replace("\\", "/").strip("/")

    if flatten:
        uploaded_name = uploaded_name.split("/")[-1]

    raw_path = f"{target_folder}/{uploaded_name}" if target_folder else uploaded_name
    return safe_norm_path(raw_path)


def should_ignore_path(path: str, ignore_dirs: set[str], ignore_files: set[str]) -> Tuple[bool, str]:
    clean = path.replace("\\", "/").strip("/")
    if not clean:
        return True, "empty path"
    parts = clean.split("/")
    filename = parts[-1]

    if clean in ignore_files or clean in ignore_dirs:
        return True, "ignored path"
    if clean.endswith(".streamlit/secrets.toml") or "/.streamlit/secrets.toml" in clean:
        return True, "Streamlit secrets file"
    if filename in ignore_files:
        return True, "ignored file"
    if clean.startswith("__MACOSX/") or "/__MACOSX/" in clean:
        return True, "macOS archive metadata"
    for part in parts:
        if part in ignore_dirs:
            return True, f"ignored folder: {part}"
    if clean.endswith(".pyc") or clean.endswith(".pyo"):
        return True, "compiled Python cache"
    return False, ""


def parse_ignore_text(value: str) -> set[str]:
    items = set(DEFAULT_IGNORE_DIRS)
    for raw in (value or "").splitlines():
        cleaned = raw.strip().strip("/")
        if cleaned and not cleaned.startswith("#"):
            items.add(cleaned)
    return items


def find_common_root(paths: Sequence[str]) -> str:
    if not paths:
        return ""
    first_parts = paths[0].split("/")
    if len(first_parts) <= 1:
        return ""
    candidate = first_parts[0]
    if candidate and all(p.startswith(candidate + "/") for p in paths):
        return candidate
    return ""


def remove_common_root(path: str, common_root: str) -> str:
    if common_root and path.startswith(common_root + "/"):
        return path[len(common_root) + 1 :]
    return path


def open_zip_to_plan(
    zip_bytes: bytes,
    *,
    zip_display_name: str,
    target_folder: str,
    strip_root: bool,
    flatten: bool,
    ignore_dirs: set[str],
    ignore_files: set[str],
    max_file_mb: int,
) -> ZipOpenResult:
    plan: List[UploadPlanItem] = []
    skipped: List[Tuple[str, str]] = []
    max_file_bytes = max(1, max_file_mb) * 1024 * 1024

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        infos = zf.infolist()
        file_names = []
        for info in infos:
            raw_name = info.filename.replace("\\", "/").strip("/")
            if not raw_name or info.is_dir():
                continue
            ignored, reason = should_ignore_path(raw_name, ignore_dirs, ignore_files)
            if ignored:
                skipped.append((raw_name, reason))
                continue
            try:
                safe_norm_path(raw_name)
            except Exception as exc:
                skipped.append((raw_name, str(exc)))
                continue
            file_names.append(raw_name)

        common_root = find_common_root(file_names) if strip_root else ""

        seen_paths: set[str] = set()
        for info in infos:
            raw_name = info.filename.replace("\\", "/").strip("/")
            if not raw_name or info.is_dir():
                continue
            ignored, reason = should_ignore_path(raw_name, ignore_dirs, ignore_files)
            if ignored:
                continue
            try:
                safe_norm_path(raw_name)
            except Exception:
                continue

            adjusted_name = remove_common_root(raw_name, common_root)
            if not adjusted_name:
                skipped.append((raw_name, "common root folder only"))
                continue
            if info.file_size > max_file_bytes:
                skipped.append((raw_name, f"over max file size: {max_file_mb} MB"))
                continue
            if info.file_size > MAX_GITHUB_FILE_BYTES:
                skipped.append((raw_name, "over GitHub 100 MB file limit"))
                continue

            try:
                content = zf.read(info)
                repo_path = normalize_repo_path(target_folder, adjusted_name, flatten=flatten)
            except zipfile.BadZipFile:
                raise
            except Exception as exc:
                skipped.append((raw_name, str(exc)))
                continue

            if repo_path in seen_paths:
                root, ext = os.path.splitext(repo_path)
                repo_path = f"{root}-{len(seen_paths) + 1}{ext}"
            seen_paths.add(repo_path)

            plan.append(
                UploadPlanItem(
                    display_name=raw_name,
                    repo_path=repo_path,
                    size_bytes=len(content),
                    content=content,
                    source=zip_display_name,
                )
            )

    return ZipOpenResult(plan=plan, skipped=skipped, common_root=common_root, total_entries=len(infos))


def make_upload_plan(uploaded_files: Iterable[Any], target_folder: str, flatten: bool) -> List[UploadPlanItem]:
    plan: List[UploadPlanItem] = []
    seen_paths: set[str] = set()

    for file in uploaded_files:
        content = file.getvalue()
        repo_path = normalize_repo_path(target_folder, file.name, flatten)
        if len(content) > MAX_GITHUB_FILE_BYTES:
            raise ValueError(f"GitHub rejects files larger than 100 MB: {file.name}")
        if repo_path in seen_paths:
            root, ext = os.path.splitext(repo_path)
            repo_path = f"{root}-{len(seen_paths) + 1}{ext}"
        seen_paths.add(repo_path)
        plan.append(UploadPlanItem(display_name=file.name, repo_path=repo_path, size_bytes=len(content), content=content))
    return plan


def bytes_to_label(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def plan_to_csv(items: Sequence[UploadPlanItem]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["source", "original_file", "github_path", "size_bytes", "size"])
    writer.writeheader()
    for item in items:
        writer.writerow(
            {
                "source": item.source,
                "original_file": item.display_name,
                "github_path": item.repo_path,
                "size_bytes": item.size_bytes,
                "size": bytes_to_label(item.size_bytes),
            }
        )
    return output.getvalue().encode("utf-8")


def results_to_csv(results: List[Dict[str, Any]]) -> bytes:
    output = io.StringIO()
    fieldnames = ["status", "path", "message", "html_url", "commit_url", "files", "commit_sha"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in results:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue().encode("utf-8")


def validate_branch(branch: str) -> None:
    if not branch or not SAFE_BRANCH_RE.match(branch):
        raise ValueError("Branch name looks invalid. Use letters, numbers, dashes, underscores, dots, or slashes.")


def is_probably_text(path: str, content: bytes) -> bool:
    lower = path.lower()
    _, ext = os.path.splitext(lower)
    if lower.endswith(".env.example") or os.path.basename(lower) in {"dockerfile", "makefile", "license"}:
        return True
    if ext not in TEXT_EXTENSIONS:
        return False
    sample = content[:4000]
    return b"\x00" not in sample


def preview_file_body(item: UploadPlanItem) -> None:
    if not is_probably_text(item.repo_path, item.content):
        st.info("Binary or unsupported preview type.")
        return
    try:
        text = item.content.decode("utf-8")
    except UnicodeDecodeError:
        text = item.content.decode("latin-1", errors="replace")
    st.code(text[:8000], language="text")
    if len(text) > 8000:
        st.caption("Preview truncated after 8,000 characters.")


def sidebar_settings() -> Dict[str, Any]:
    st.sidebar.title("GitHub API")
    st.sidebar.caption("Use a fine-grained token or store it in Streamlit secrets as `GITHUB_TOKEN`.")

    secret_token = get_secret("GITHUB_TOKEN", "")
    token = st.sidebar.text_input(
        "GitHub token",
        value=secret_token,
        type="password",
        help="Needs repository Contents read/write access for the target repo.",
    )

    col_a, col_b = st.sidebar.columns(2)
    with col_a:
        owner = st.text_input("Owner", value=get_secret("GITHUB_OWNER", ""), placeholder="octocat")
    with col_b:
        repo = st.text_input("Repo", value=get_secret("GITHUB_REPO", ""), placeholder="my-repo")

    branch = st.sidebar.text_input("Branch", value=get_secret("GITHUB_BRANCH", "main"))
    target_folder = st.sidebar.text_input("Target folder/path", value=get_secret("GITHUB_TARGET_FOLDER", ""), help="Leave blank to upload to repo root.")
    api_base = st.sidebar.text_input("GitHub API base URL", value=get_secret("GITHUB_API_BASE", DEFAULT_API_BASE))

    with st.sidebar.expander("Commit options", expanded=False):
        commit_message = st.text_input("Commit message", value="Upload ZIP/project from Streamlit")
        overwrite = st.checkbox("Overwrite existing paths", value=True, help="Bulk ZIP commits replace matching paths in the target branch.")
        flatten = st.checkbox("Flatten paths", value=False, help="Keeps only filenames. Usually leave off for ZIP projects.")
        bulk_commit = st.checkbox("One commit for project upload", value=True, help="Best for ZIP projects. Creates blobs/tree/one commit instead of one commit per file.")
        committer_name = st.text_input("Committer name", value=get_secret("GITHUB_COMMITTER_NAME", ""))
        committer_email = st.text_input("Committer email", value=get_secret("GITHUB_COMMITTER_EMAIL", ""))

    with st.sidebar.expander("ZIP open/extract options", expanded=False):
        strip_root = st.checkbox("Remove top ZIP folder", value=True, help="Turns my-app/app.py into app.py before adding target folder.")
        max_file_mb = st.number_input("Max individual file size MB", min_value=1, max_value=100, value=DEFAULT_MAX_FILE_MB, step=1)
        ignore_extra = st.text_area(
            "Ignored folders/files, one per line",
            value="\n".join(sorted(DEFAULT_IGNORE_DIRS)),
            help="These are skipped when opening a ZIP. Keep secrets.toml ignored.",
            height=160,
        )

    return {
        "token": token,
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "target_folder": target_folder,
        "api_base": api_base,
        "commit_message": commit_message,
        "overwrite": overwrite,
        "flatten": flatten,
        "bulk_commit": bulk_commit,
        "committer_name": committer_name,
        "committer_email": committer_email,
        "strip_root": strip_root,
        "max_file_mb": int(max_file_mb),
        "ignore_dirs": parse_ignore_text(ignore_extra),
        "ignore_files": set(DEFAULT_IGNORE_FILES),
    }


def render_plan_summary(plan: Sequence[UploadPlanItem], skipped: Optional[Sequence[Tuple[str, str]]] = None) -> None:
    total_size = sum(item.size_bytes for item in plan)
    c1, c2, c3 = st.columns(3)
    c1.metric("Files ready", len(plan))
    c2.metric("Total size", bytes_to_label(total_size))
    c3.metric("Skipped", len(skipped or []))

    if not plan:
        st.warning("No files are ready to upload after filtering.")
        return

    rows = [
        {
            "Original file": item.display_name,
            "GitHub path": item.repo_path,
            "Size": bytes_to_label(item.size_bytes),
            "Source": item.source,
        }
        for item in plan
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True, height=min(520, 80 + len(rows) * 35))
    st.download_button("Download file plan CSV", data=plan_to_csv(plan), file_name="github_upload_plan.csv", mime="text/csv")

    with st.expander("Open and preview one file", expanded=False):
        labels = [f"{idx + 1}. {item.repo_path} ({bytes_to_label(item.size_bytes)})" for idx, item in enumerate(plan)]
        selected = st.selectbox("Choose a file", labels)
        idx = labels.index(selected)
        preview_file_body(plan[idx])

    if skipped:
        with st.expander("Skipped files", expanded=False):
            st.dataframe([{"File": path, "Reason": reason} for path, reason in skipped], use_container_width=True, hide_index=True)


def upload_plan_to_github(settings: Dict[str, Any], plan: Sequence[UploadPlanItem], dry_run: bool) -> None:
    if not plan:
        st.error("Nothing to upload.")
        return

    validate_branch(settings["branch"])
    if dry_run:
        st.success("Dry run passed. No files were uploaded.")
        return

    client = GitHubClient(
        token=settings["token"],
        owner=settings["owner"],
        repo=settings["repo"],
        api_base=settings["api_base"],
    )

    progress = st.progress(0, text="Starting upload…")
    results: List[Dict[str, Any]] = []
    errors: List[Tuple[str, str]] = []

    if settings["bulk_commit"] and len(plan) > 1:
        bulk_plan = list(plan)
        if not settings["overwrite"]:
            filtered: List[UploadPlanItem] = []
            for idx, item in enumerate(bulk_plan, start=1):
                progress.progress((idx - 1) / len(bulk_plan), text=f"Checking existing path {idx}/{len(bulk_plan)}: {item.repo_path}")
                try:
                    existing_sha = client.get_file_sha(item.repo_path, settings["branch"])
                    if existing_sha:
                        results.append({
                            "status": "skipped",
                            "path": item.repo_path,
                            "message": "File already exists and overwrite is off.",
                            "html_url": "",
                            "commit_url": "",
                        })
                    else:
                        filtered.append(item)
                except Exception as exc:
                    errors.append((item.repo_path, str(exc)))
            bulk_plan = filtered

        if bulk_plan:
            def cb(idx: int, total: int, text: str) -> None:
                progress.progress(min(idx / max(total, 1), 1.0), text=text)

            try:
                result = client.commit_many_files(
                    items=bulk_plan,
                    branch=settings["branch"],
                    message=settings["commit_message"],
                    committer_name=settings["committer_name"].strip() or None,
                    committer_email=settings["committer_email"].strip() or None,
                    progress_callback=cb,
                )
                results.append(result)
            except Exception as exc:
                errors.append(("bulk project commit", str(exc)))
        elif not errors:
            progress.empty()
            st.warning("Every file already exists and overwrite is off. Nothing new was committed.")
            if results:
                st.dataframe(results, use_container_width=True, hide_index=True)
            return
    else:
        for idx, item in enumerate(plan, start=1):
            progress.progress((idx - 1) / len(plan), text=f"Uploading {item.repo_path}…")
            try:
                result = client.create_or_update_file(
                    repo_path=item.repo_path,
                    content=item.content,
                    branch=settings["branch"],
                    message=settings["commit_message"],
                    overwrite=settings["overwrite"],
                    committer_name=settings["committer_name"].strip() or None,
                    committer_email=settings["committer_email"].strip() or None,
                )
                results.append(result)
            except Exception as exc:
                errors.append((item.repo_path, str(exc)))
            time.sleep(0.03)
            progress.progress(idx / len(plan), text=f"Processed {idx}/{len(plan)} file(s)")

    progress.empty()

    if results:
        st.success(f"Finished: {len(plan)} file(s) processed.")
        st.dataframe(results, use_container_width=True, hide_index=True)
        st.download_button("Download upload log CSV", data=results_to_csv(results), file_name="github_upload_log.csv", mime="text/csv")
        for result in results:
            if result.get("commit_url"):
                st.link_button("Open GitHub commit", result["commit_url"])

    if errors:
        st.error(f"{len(errors)} upload step(s) failed.")
        for path, message in errors:
            st.warning(f"**{path}** — {message}")


def zip_upload_tab(settings: Dict[str, Any]) -> None:
    st.subheader("Upload ZIP, open it, preview files, then push to GitHub")
    st.caption("Best for Streamlit apps, WordPress plugins, static sites, Python projects, or any folder you zipped on your computer.")

    zip_file = st.file_uploader("Choose a .zip project file", type=["zip"], accept_multiple_files=False)
    if not zip_file:
        st.info("Upload a ZIP file to open and preview its contents.")
        return

    zip_bytes = zip_file.getvalue()
    st.success(f"Opened ZIP: {zip_file.name} · {bytes_to_label(len(zip_bytes))}")

    try:
        opened = open_zip_to_plan(
            zip_bytes,
            zip_display_name=zip_file.name,
            target_folder=settings["target_folder"],
            strip_root=settings["strip_root"],
            flatten=settings["flatten"],
            ignore_dirs=settings["ignore_dirs"],
            ignore_files=settings["ignore_files"],
            max_file_mb=settings["max_file_mb"],
        )
    except zipfile.BadZipFile:
        st.error("This does not look like a valid ZIP file.")
        return
    except Exception as exc:
        st.error(f"Could not open ZIP: {exc}")
        return

    if opened.common_root:
        st.caption(f"Removed top folder from ZIP: `{opened.common_root}/`")
    render_plan_summary(opened.plan, opened.skipped)

    st.divider()
    left, right = st.columns([1, 2])
    dry_run = left.checkbox("Dry run only", value=False, key="zip_dry_run")
    upload_archive_too = left.checkbox("Also upload original ZIP", value=False, help="Useful if you want the archive stored in GitHub too.")
    start_upload = left.button("Upload opened ZIP to GitHub", type="primary", use_container_width=True)

    final_plan = list(opened.plan)
    if upload_archive_too:
        archive_name = normalize_repo_path(settings["target_folder"], zip_file.name, flatten=True)
        final_plan.append(UploadPlanItem(zip_file.name, archive_name, len(zip_bytes), zip_bytes, source="original ZIP archive"))
        right.info(f"Original ZIP will also be uploaded as `{archive_name}`.")

    if start_upload:
        try:
            upload_plan_to_github(settings, final_plan, dry_run)
        except Exception as exc:
            st.error(str(exc))


def files_folder_tab(settings: Dict[str, Any]) -> None:
    st.subheader("Upload files or a local folder")
    upload_mode = st.radio(
        "Upload mode",
        ["Multiple files", "Folder upload"],
        horizontal=True,
        help="Folder upload depends on your browser and Streamlit version.",
    )

    uploader_kwargs: Dict[str, Any] = {
        "label": "Choose files" if upload_mode == "Multiple files" else "Choose a folder",
        "accept_multiple_files": True if upload_mode == "Multiple files" else "directory",
        "label_visibility": "visible",
    }
    uploaded_files = st.file_uploader(**uploader_kwargs)

    if not uploaded_files:
        st.info("Choose files to preview the upload plan.")
        return

    try:
        plan = make_upload_plan(uploaded_files, settings["target_folder"], settings["flatten"])
    except Exception as exc:
        st.error(f"Could not build upload plan: {exc}")
        return

    render_plan_summary(plan)

    st.divider()
    left, _right = st.columns([1, 2])
    dry_run = left.checkbox("Dry run only", value=False, key="files_dry_run")
    start_upload = left.button("Upload files to GitHub", type="primary", use_container_width=True)

    if start_upload:
        try:
            upload_plan_to_github(settings, plan, dry_run)
        except Exception as exc:
            st.error(str(exc))


def help_tab() -> None:
    st.subheader("Setup help")
    st.markdown(
        """
### Token permissions
Create a GitHub fine-grained personal access token for the target repository and give it **Contents: Read and write** permission.

### ZIP workflow
1. Zip your Streamlit project folder.
2. Upload the `.zip` here.
3. The app opens the ZIP, removes junk folders like `.git`, `node_modules`, and `.streamlit/secrets.toml`, then shows the upload plan.
4. Click **Upload opened ZIP to GitHub**.
5. Use **One commit for project upload** in the sidebar for cleaner GitHub history.

### Recommended Streamlit project files
Your ZIP should usually include:

```text
app.py
requirements.txt
README.md
.streamlit/config.toml
```

Do not upload `.streamlit/secrets.toml`. Use Streamlit Cloud secrets instead.
        """
    )


def main() -> None:
    st.set_page_config(page_title="Streamlit ZIP → GitHub Uploader", page_icon="📦", layout="wide")

    st.title("📦 Streamlit ZIP → GitHub Uploader")
    st.write(
        "Upload a ZIP, open and preview its contents, then commit the extracted project files directly to GitHub. "
        "GitHub API settings are in the sidebar."
    )

    settings = sidebar_settings()

    with st.sidebar:
        st.divider()
        if st.button("Test GitHub connection", use_container_width=True):
            try:
                validate_branch(settings["branch"])
                client = GitHubClient(
                    token=settings["token"],
                    owner=settings["owner"],
                    repo=settings["repo"],
                    api_base=settings["api_base"],
                )
                repo_info = client.check_repo()
                default_branch = repo_info.get("default_branch", "unknown")
                private = "private" if repo_info.get("private") else "public"
                st.success(f"Connected to {settings['owner']}/{settings['repo']} ({private}). Default branch: {default_branch}")
            except Exception as exc:
                st.error(str(exc))

    tab_zip, tab_files, tab_help = st.tabs(["Upload ZIP + Open", "Files / Folder", "Help"])
    with tab_zip:
        zip_upload_tab(settings)
    with tab_files:
        files_folder_tab(settings)
    with tab_help:
        help_tab()


if __name__ == "__main__":
    main()
