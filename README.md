# Streamlit → GitHub File Uploader

A clean Streamlit app that uploads files or folders directly into a GitHub repository through the GitHub REST API.

## Features

- GitHub API settings in the sidebar
- Fine-grained personal access token support
- Single/multiple file upload
- Folder upload mode when supported by your browser and Streamlit version
- Target folder/path control
- Branch selector
- Commit message control
- Optional committer name/email
- Existing-file overwrite toggle
- Dry-run preview
- Upload progress bar
- Results table and downloadable CSV upload log
- Safe path normalization to block unsafe paths such as `../`

## Files

```text
streamlit_github_uploader/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

## GitHub token setup

Create a GitHub fine-grained personal access token limited to the repository you want to upload into.

Recommended repository permission:

- **Contents: Read and write**

The app uses GitHub's repository contents endpoint to create or update files. Updating an existing file requires the current file SHA, so the app checks whether a file already exists before uploading.

## Local setup

```bash
cd streamlit_github_uploader
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# .venv\Scripts\activate   # Windows PowerShell
pip install -r requirements.txt
streamlit run app.py
```

## Using sidebar API fields

Paste these values in the sidebar:

- GitHub token
- Owner, for example `octocat`
- Repo, for example `my-streamlit-files`
- Branch, usually `main`
- Target folder/path, for example `uploads`, `client-files`, or `public/assets`
- API base URL, usually `https://api.github.com`

Then upload files and click **Upload to GitHub**.

## Using Streamlit secrets

For local development, copy:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml`:

```toml
GITHUB_TOKEN = "github_pat_your_token_here"
GITHUB_OWNER = "your-user-or-org"
GITHUB_REPO = "your-repo"
GITHUB_BRANCH = "main"
GITHUB_TARGET_FOLDER = "uploads"
```

Do **not** commit `.streamlit/secrets.toml` to GitHub.

For Streamlit Community Cloud, add these values in your app's Secrets settings instead.

## Deploy to Streamlit Community Cloud

1. Push this project to GitHub.
2. Go to Streamlit Community Cloud.
3. Create a new app from the repo.
4. Select `app.py` as the entrypoint.
5. Add secrets in the app settings.
6. Deploy.

## Notes

- Large files are limited by Streamlit upload limits and GitHub API/repository limits.
- For many large files, GitHub releases, Git LFS, or cloud storage may be a better fit.
- Folder upload depends on browser support.
