# Streamlit ZIP → GitHub Uploader

A Streamlit app that lets you upload a `.zip`, open and preview the files inside, then commit the extracted project into a GitHub repository.

It also supports normal multi-file upload and folder upload.

## Features

- GitHub API token/settings in the sidebar
- Upload a ZIP project file
- Open and preview ZIP contents before upload
- Remove the top-level ZIP folder automatically
- Skip junk or dangerous files by default:
  - `.git`
  - `node_modules`
  - `.venv`, `venv`, `env`
  - `__pycache__`
  - `.DS_Store`
  - `.streamlit/secrets.toml`
- Upload extracted ZIP files to GitHub
- Optional upload of the original ZIP archive too
- One clean commit for a full project upload
- File/folder upload tab
- Dry-run mode
- Upload plan CSV export
- Upload log CSV export
- Safe Streamlit secrets support

## Run locally

```bash
cd streamlit_github_uploader
pip install -r requirements.txt
streamlit run app.py
```

## GitHub token setup

Create a GitHub fine-grained personal access token for the target repository.

Minimum permission:

```text
Repository permissions → Contents → Read and write
```

Paste the token into the sidebar, or store it in Streamlit secrets.

## Streamlit secrets

Create this file locally:

```text
.streamlit/secrets.toml
```

Example:

```toml
GITHUB_TOKEN = "github_pat_your_token_here"
GITHUB_OWNER = "your-github-username-or-org"
GITHUB_REPO = "your-repo-name"
GITHUB_BRANCH = "main"
GITHUB_TARGET_FOLDER = ""
```

Never commit your real `secrets.toml` file.

## Best ZIP workflow

1. Put your Streamlit files in one folder.
2. Make sure the folder includes:

```text
app.py
requirements.txt
README.md
.streamlit/config.toml
```

3. Zip the folder.
4. Open this app.
5. Select the **Upload ZIP + Open** tab.
6. Upload the ZIP.
7. Preview the opened files.
8. Click **Upload opened ZIP to GitHub**.

## Notes

- GitHub rejects individual files larger than 100 MB.
- The app defaults to a 25 MB individual-file limit to avoid accidental huge uploads.
- For large projects, keep **One commit for project upload** enabled in the sidebar.
- Do not upload `.streamlit/secrets.toml`; it is ignored by default.
