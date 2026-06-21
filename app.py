"""Streamlit GitHub Uploader

Upload one file, many files, or a folder from a Streamlit app directly into a
GitHub repository through the GitHub REST Contents API.
"""

from __future__ import annotations

import base64
import csv
import io
import os
import posixpath
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import streamlit as st


GITHUB_API_VERSION = "2022-11-28"
DEFAULT_API_BASE = "https://api.github.com"
SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")


@dataclass
class UploadPlanItem:
    display_name: str
    repo_path: str
    size_bytes: int
    content: bytes


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
        timeout = kwargs.pop("timeout", 45)
        resp = requests.request(method, self._url(path), headers=self.headers, timeout=timeout, **kwargs)
        return resp

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
            timeout=90,
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

    @staticmethod
    def _raise_api_error(resp: requests.Response, fallback: str) -> None:
        try:
            payload = resp.json()
        except Exception:
            payload = {"message": resp.text[:800]}
        api_message = payload.get("message") or fallback
        raise GitHubAPIError(f"{fallback} GitHub said: {api_message}", resp.status_code, payload)


def quote_path(path: str) -> str:
    """Quote a GitHub contents path without quoting forward slashes."""
    from urllib.parse import quote

    return "/".join(quote(part, safe="") for part in path.split("/"))


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)  # type: ignore[attr-defined]
        return str(value) if value is not None else default
    except Exception:
        return default


def sanitize_segment(segment: str) -> str:
    segment = segment.strip().replace("\\", "/")
    segment = segment.strip("/")
    return segment


def normalize_repo_path(target_folder: str, uploaded_name: str, flatten: bool) -> str:
    target_folder = sanitize_segment(target_folder)
    uploaded_name = uploaded_name.replace("\\", "/").strip("/")

    if flatten:
        uploaded_name = uploaded_name.split("/")[-1]

    raw_path = f"{target_folder}/{uploaded_name}" if target_folder else uploaded_name
    normalized = posixpath.normpath(raw_path).replace("\\", "/")

    if normalized in (".", ""):
        raise ValueError("Upload path cannot be empty.")
    if normalized.startswith("../") or normalized == ".." or "/../" in normalized:
        raise ValueError(f"Unsafe path rejected: {raw_path}")
    if normalized.startswith("/"):
        raise ValueError(f"Unsafe absolute path rejected: {raw_path}")
    return normalized


def make_upload_plan(uploaded_files: Iterable[Any], target_folder: str, flatten: bool) -> List[UploadPlanItem]:
    plan: List[UploadPlanItem] = []
    seen_paths: set[str] = set()

    for file in uploaded_files:
        content = file.getvalue()
        repo_path = normalize_repo_path(target_folder, file.name, flatten)
        if repo_path in seen_paths:
            root, ext = os.path.splitext(repo_path)
            repo_path = f"{root}-{len(seen_paths) + 1}{ext}"
        seen_paths.add(repo_path)
        plan.append(
            UploadPlanItem(
                display_name=file.name,
                repo_path=repo_path,
                size_bytes=len(content),
                content=content,
            )
        )
    return plan


def bytes_to_label(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def results_to_csv(results: List[Dict[str, Any]]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["status", "path", "message", "html_url", "commit_url"])
    writer.writeheader()
    for row in results:
        writer.writerow({key: row.get(key, "") for key in writer.fieldnames or []})
    return output.getvalue().encode("utf-8")


def validate_branch(branch: str) -> None:
    if not branch or not SAFE_BRANCH_RE.match(branch):
        raise ValueError("Branch name looks invalid. Use letters, numbers, dashes, underscores, dots, or slashes.")


def sidebar_settings() -> Dict[str, Any]:
    st.sidebar.title("GitHub API")
    st.sidebar.caption("Paste a GitHub fine-grained token or store it in Streamlit secrets as `GITHUB_TOKEN`.")

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
    target_folder = st.sidebar.text_input("Target folder/path", value=get_secret("GITHUB_TARGET_FOLDER", "uploads"))
    api_base = st.sidebar.text_input("GitHub API base URL", value=get_secret("GITHUB_API_BASE", DEFAULT_API_BASE))

    with st.sidebar.expander("Commit options", expanded=False):
        commit_message = st.text_input("Commit message", value="Upload files from Streamlit")
        overwrite = st.checkbox("Overwrite existing files", value=True)
        flatten = st.checkbox("Flatten folder paths", value=False, help="Keeps only the filename when uploading a folder.")
        committer_name = st.text_input("Committer name", value=get_secret("GITHUB_COMMITTER_NAME", ""))
        committer_email = st.text_input("Committer email", value=get_secret("GITHUB_COMMITTER_EMAIL", ""))

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
        "committer_name": committer_name,
        "committer_email": committer_email,
    }


def main() -> None:
    st.set_page_config(page_title="Streamlit → GitHub Uploader", page_icon="⬆️", layout="wide")

    st.title("⬆️ Streamlit → GitHub File Uploader")
    st.write(
        "Upload files from a clean Streamlit interface and commit them directly into a GitHub repository. "
        "All GitHub API settings live in the sidebar."
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

    upload_mode = st.radio(
        "Upload mode",
        ["Multiple files", "Folder upload"],
        horizontal=True,
        help="Folder upload support depends on the browser and Streamlit version.",
    )

    uploader_kwargs: Dict[str, Any] = {
        "label": "Choose files" if upload_mode == "Multiple files" else "Choose a folder",
        "accept_multiple_files": True if upload_mode == "Multiple files" else "directory",
        "label_visibility": "visible",
    }
    uploaded_files = st.file_uploader(**uploader_kwargs)

    if not uploaded_files:
        st.info("Choose files to preview the upload plan.")
        with st.expander("Recommended token permissions"):
            st.markdown(
                "Create a GitHub fine-grained personal access token limited to this repository. "
                "Give it **Contents: Read and write** permission. Do not commit tokens into your repo."
            )
        return

    try:
        plan = make_upload_plan(uploaded_files, settings["target_folder"], settings["flatten"])
    except Exception as exc:
        st.error(f"Could not build upload plan: {exc}")
        return

    total_size = sum(item.size_bytes for item in plan)
    st.subheader("Upload preview")
    st.caption(f"{len(plan)} file(s), total size {bytes_to_label(total_size)}")

    preview_rows = [
        {
            "Original file": item.display_name,
            "GitHub path": item.repo_path,
            "Size": bytes_to_label(item.size_bytes),
        }
        for item in plan
    ]
    st.dataframe(preview_rows, use_container_width=True, hide_index=True)

    left, right = st.columns([1, 2])
    dry_run = left.checkbox("Dry run only", value=False, help="Preview without calling GitHub.")
    start_upload = left.button("Upload to GitHub", type="primary", use_container_width=True)

    if dry_run:
        right.success("Dry run is on. Click upload to validate settings without sending files.")

    if not start_upload:
        return

    try:
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
            time.sleep(0.05)
            progress.progress(idx / len(plan), text=f"Processed {idx}/{len(plan)} file(s)")

        progress.empty()

        if results:
            st.success(f"Finished: {len(results)} file(s) processed.")
            st.dataframe(results, use_container_width=True, hide_index=True)
            st.download_button(
                "Download upload log CSV",
                data=results_to_csv(results),
                file_name="github_upload_log.csv",
                mime="text/csv",
            )

        if errors:
            st.error(f"{len(errors)} file(s) failed.")
            for path, message in errors:
                st.warning(f"**{path}** — {message}")

    except Exception as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
