# Direct ZIP → GitHub Streamlit Uploader

A no-review Streamlit app for uploading a `.zip` project directly to GitHub.

You choose a ZIP, click one button, and the app extracts the project, skips junk/secrets, and pushes the files to a GitHub repository.

## What was fixed in this version

- The Direct ZIP button now performs the full action immediately.
- New or empty repositories are handled more safely.
- New repo creation uses `auto_init=true` so GitHub creates a default branch.
- If an existing repo has no branch yet, the app can initialize it with the uploaded ZIP files.
- Added a more reliable default upload engine using the GitHub Contents API.
- Added an optional single-commit engine using the Git Database API.
- Added clearer GitHub error messages and a connection-test tab.
- Added better ZIP validation, ZIP corruption checks, and zip-slip path protection.
- Added safer secret filtering.

## Features

- Direct `.zip` upload to GitHub
- No code preview/review required
- GitHub token/API fields in the sidebar
- Owner, repo, branch, target folder, and commit message settings
- Create repo if missing
- Create branch if missing
- Works better with empty/new repos
- Compatibility upload mode for reliability
- Single-commit upload mode for cleaner Git history
- Overwrite existing files toggle
- Optional clean/replace target folder mode
- Removes the top ZIP folder automatically
- Skips `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.env`, `.streamlit/secrets.toml`, and credential-looking files
- Direct files/folder uploader included
- Progress bar, GitHub commit link, uploaded files link, and CSV logs
- Streamlit secrets support
- GitHub Enterprise API base URL support

## Quick start

```bash
cd streamlit_github_direct_fixed
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
streamlit run app.py
```

## Token setup

Create a GitHub fine-grained personal access token.

For normal uploading, give it:

- Repository access to the target repository
- Contents: Read and write

To create repositories from the app, also allow the token to create repositories for your user or organization.

## Local secrets setup

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

## Upload engines

### Compatibility mode - most reliable

Default. Uses the GitHub Repository Contents API. Best when the previous direct ZIP uploader failed, especially for new repositories, branch issues, or normal small-to-medium projects.

This may create more than one commit because GitHub's contents endpoint commits file-by-file.

### Single commit mode - faster

Uses GitHub's Git Database API to create blobs, one tree, one commit, and then update the branch reference.

Use this when you want one clean commit for the whole ZIP.

## Recommended ZIP structure

Your ZIP can look like this:

```text
my-app/
  app.py
  requirements.txt
  README.md
  .streamlit/
    config.toml
```

With **Remove top ZIP folder** on, GitHub receives:

```text
app.py
requirements.txt
README.md
.streamlit/config.toml
```

## Target folder examples

Blank target folder uploads to repo root.

Target folder:

```text
apps/client-dashboard
```

Uploads to:

```text
apps/client-dashboard/app.py
apps/client-dashboard/requirements.txt
```

## Troubleshooting

If upload fails:

1. Open the **Connection** tab and test GitHub access.
2. Use **Compatibility mode - most reliable**.
3. Turn on **Create repo if missing** if the repo does not exist.
4. Leave **Create branch if missing** on.
5. Make sure the token has **Contents: Read and write** permission.
6. Keep individual files under 100 MB.
7. Keep secret filtering on unless you know the ZIP is safe.

## Files

```text
app.py
requirements.txt
README.md
.streamlit/config.toml
.streamlit/secrets.toml.example
.gitignore
```
