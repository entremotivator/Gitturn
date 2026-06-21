# Direct ZIP → GitHub Streamlit Uploader

A one-click Streamlit app that uploads a `.zip` project, opens it in memory, filters junk/secrets, and pushes the extracted files directly to a GitHub repository as one clean commit.

This version removes the code-review step. The user selects a ZIP, fills in GitHub settings in the sidebar, and clicks **Upload ZIP to GitHub now**.

## Main features

- Upload a ZIP project and push it straight to GitHub
- GitHub token, owner, repo, branch, and target folder in the sidebar
- Uses GitHub Git Database API for one commit instead of one commit per file
- Can create the repository if it does not exist
- Can create the target branch if it does not exist
- Can overwrite existing files
- Optional clean/replace mode for deleting old files inside the target folder before uploading
- Removes the top ZIP folder automatically
- Skips dangerous or unnecessary files by default:
  - `.git`
  - `node_modules`
  - `.venv`, `venv`, `env`
  - `__pycache__`
  - build folders
  - `.env`
  - `.streamlit/secrets.toml`
  - common credential-looking files
- Supports regular multi-file upload and browser folder upload
- Progress bar while pushing to GitHub
- GitHub commit link after upload
- Uploaded file list CSV and push log CSV
- Streamlit secrets support
- GitHub Enterprise API base URL support

## Quick start

```bash
cd streamlit_github_direct_pusher
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
streamlit run app.py
```

## GitHub token setup

Create a GitHub fine-grained personal access token.

For uploading to an existing repository, give the token:

- Repository access: the target repository
- Permissions: **Contents: Read and write**

For creating a new repository from the app, the token also needs permission to create repositories for the user or organization.

## Streamlit secrets setup

For local development, copy:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml`:

```toml
GITHUB_TOKEN = "github_pat_xxxxxxxxxxxxxxxxx"
GITHUB_OWNER = "your-github-user-or-org"
GITHUB_REPO = "your-repo-name"
GITHUB_BRANCH = "main"
GITHUB_TARGET_FOLDER = ""
```

Do not commit `.streamlit/secrets.toml`.

## Normal workflow

1. Zip your Streamlit app or project folder.
2. Open this app.
3. Paste your GitHub token in the sidebar.
4. Enter owner, repo, branch, and optional target folder.
5. Upload the ZIP.
6. Click **Upload ZIP to GitHub now**.
7. Open the GitHub commit link after the push finishes.

## Recommended ZIP structure

Your ZIP can look like this:

```text
my-streamlit-app/
  app.py
  requirements.txt
  README.md
  .streamlit/
    config.toml
```

With **Remove top ZIP folder** enabled, it uploads to GitHub as:

```text
app.py
requirements.txt
README.md
.streamlit/config.toml
```

## Target folder examples

Leave `Target folder` blank to upload into the root of the repo.

Use a folder path to upload inside a subfolder:

```text
apps/client-dashboard
```

The app will commit files like:

```text
apps/client-dashboard/app.py
apps/client-dashboard/requirements.txt
```

## Clean/replace mode

The sidebar includes **Delete old files in target folder before upload**.

Use this only when you want the GitHub target folder to match the ZIP exactly. For safety, the app requires typing:

```text
CLEAN
```

before it deletes old files in the target folder.

## Notes and limits

- GitHub rejects individual files over 100 MB through this API path.
- Large projects with thousands of files may be slow because every file becomes a Git blob.
- Keep `Skip secrets / credentials` enabled unless you are absolutely sure the ZIP has no secrets.
- The app works best for Streamlit apps, WordPress plugin ZIPs, static sites, Python projects, and small web projects.

## Files in this project

```text
app.py
requirements.txt
README.md
.streamlit/config.toml
.streamlit/secrets.toml.example
.gitignore
```
