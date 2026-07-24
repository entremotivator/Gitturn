# GitHubUpload 2.0

GitHubUpload is a WordPress administration plugin that publishes browser-selected folders or ZIP archives to GitHub.com or GitHub Enterprise through the GitHub REST API.

Each operation creates Git blobs, builds a new tree from the current branch tree, creates one commit, and advances the selected branch without force-pushing history.

## Highlights

- Upload complete folders while preserving nested relative paths.
- Upload ZIP archives and either extract them or keep them as one file.
- Connect to GitHub.com or a GitHub Enterprise Server REST endpoint.
- Discover accessible repositories and repository branches from WordPress.
- Test authentication, repository access, push permission, branch state, rate limits, API version, and request IDs.
- Configure API timeout, retry attempts, SSL verification, repository visibility, and REST API version.
- Store the token encrypted or provide it as a `wp-config.php` constant.
- Protect `.env`, `wp-config.php`, private keys, authentication files, and other sensitive paths.
- Block GitHub Actions workflow files unless workflow uploads are explicitly enabled.
- Use wildcard exclusions such as `*.log`, `build/**`, or `.cache/**`.
- Configure message templates, optional commit author details, target folders, branch creation, and upload limits.
- Keep a local success/failure history without storing uploaded file contents.

## Requirements

- WordPress 6.2 or newer.
- PHP 7.4 or newer.
- PHP `ZipArchive` when extracting ZIP archives.
- An initialized GitHub repository containing at least one commit.
- A GitHub token with access to the selected repository.

Recommended fine-grained token permissions:

- **Metadata: read** for repository discovery.
- **Contents: read and write** for Git objects, commits, and branch references.
- **Workflows: read and write** only when uploading files below `.github/workflows/`.

## Installation

1. In WordPress, open **Plugins → Add New → Upload Plugin**.
2. Upload `githubupload-v2.0.0.zip`.
3. Activate **GitHubUpload**.
4. Open **GitHubUpload → API Settings**.
5. Enter the token and API endpoint, then run connection diagnostics.
6. Load repositories and branches, save defaults, and open the Upload Center.

## GitHub.com settings

```text
API URL: https://api.github.com
API version: 2026-03-10
```

The previous supported version `2022-11-28` remains selectable for compatibility.

## GitHub Enterprise Server

Enter the full REST API root, normally:

```text
https://github.company.com/api/v3
```

GitHubUpload derives repository and commit links from this Enterprise URL.

## Production credential constants

A token in `wp-config.php` overrides the database-stored token:

```php
define( 'GITHUBUPLOAD_TOKEN', 'github_pat_REPLACE_ME' );
```

The endpoint and API version can also be locked in configuration:

```php
define( 'GITHUBUPLOAD_API_ROOT', 'https://api.github.com' );
define( 'GITHUBUPLOAD_API_VERSION', '2026-03-10' );
```

Do not commit `wp-config.php` or token values to a repository.

## Commit message variables

The default commit message supports:

- `{files}`
- `{site}`
- `{date}`
- `{time}`
- `{user}`
- `{repository}`
- `{branch}`

Example:

```text
Upload {files} files from {site} to {repository}:{branch} on {date}
```

## Security behavior

Sensitive-file protection stops the entire operation when a protected path is detected. The default list includes:

```text
.env
.env.*
wp-config.php
*.pem
*.key
*.p12
*.pfx
id_rsa
id_ed25519
auth.json
.npmrc
```

Workflow files are blocked separately unless **Allow `.github/workflows` files** is enabled. GitHub may still reject workflow changes when the token does not have the required Workflows permission.

## Upload limits

Defaults:

- 500 files per operation.
- 100 MB total.
- 95 MB per file.

WordPress hosting settings such as `post_max_size`, `upload_max_filesize`, `max_file_uploads`, memory limits, and request timeouts can impose lower limits.

## Developer filters

```php
add_filter( 'githubupload_capability', function () {
    return 'manage_options';
} );

add_filter( 'githubupload_max_files', function () {
    return 1000;
} );

add_filter( 'githubupload_max_total_bytes', function () {
    return 250 * MB_IN_BYTES;
} );

add_filter( 'githubupload_max_single_bytes', function () {
    return 95 * MB_IN_BYTES;
} );
```

## API workflow

1. Validate the selected paths, limits, exclusions, and sensitive-file rules.
2. Read the current branch reference and parent commit.
3. Create one Git blob for each eligible file.
4. Create one tree based on the current branch tree.
5. Create one commit with the current branch commit as its parent.
6. Move the branch reference forward with `force: false`.

## Release build

From the directory containing `githubupload/`:

```bash
zip -r githubupload-v2.0.0.zip githubupload \
  -x '*/.DS_Store' '*/.git/*' '*/node_modules/*'
```

## License

GPL-2.0-or-later.
