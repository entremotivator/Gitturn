=== GitHubUpload ===
Contributors: entremotivator
Tags: github, api, upload, zip, folder, deployment, repository, enterprise
Requires at least: 6.2
Tested up to: 7.0
Requires PHP: 7.4
Stable tag: 2.0.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Upload complete folders or ZIP projects to GitHub.com or GitHub Enterprise with repository discovery, API diagnostics, security controls, and atomic commits.

== Description ==

GitHubUpload adds a protected WordPress administration application for publishing project folders and ZIP archives through the GitHub REST API.

= API and connection features =

* Dedicated API Settings interface.
* GitHub.com and GitHub Enterprise Server support.
* Selectable REST API version.
* Configurable HTTPS endpoint, request timeout, retries, and SSL verification.
* Encrypted database token storage.
* Optional GITHUBUPLOAD_TOKEN wp-config.php constant.
* Optional GITHUBUPLOAD_API_ROOT and GITHUBUPLOAD_API_VERSION constants.
* Repository discovery for repositories available to the authenticated token.
* Branch discovery for the selected repository.
* Connection diagnostics for user identity, repository access, push permission, default branch, branch state, rate limits, and request ID.

= Upload features =

* Select a complete browser folder while preserving relative paths.
* Upload a ZIP archive and extract its files or retain it as one ZIP.
* Publish all selected files in one Git commit using Git blobs and trees.
* Choose the repository, branch, target directory, and commit message.
* Create a missing branch from the repository default branch.
* Replace existing files at matching paths without force-moving branch history.
* Configure reusable commit message templates.
* Optionally set commit author name and email.
* View estimated API request volume before uploading.

= Security features =

* Administrator capability checks and WordPress nonces on every action.
* Sensitive-file blocking for environment files, WordPress configuration, private keys, and authentication files.
* Separate protection for .github/workflows files.
* General wildcard exclusions such as *.log and build/**.
* Configurable total and per-file upload limits.
* Saved tokens are never returned to the browser.
* Local history stores operation metadata but not uploaded file contents.

== Installation ==

1. Upload `githubupload-v2.0.0.zip` from Plugins > Add New > Upload Plugin.
2. Activate GitHubUpload.
3. Open GitHubUpload > API Settings.
4. Add a fine-grained GitHub personal access token.
5. Use `https://api.github.com` for GitHub.com or the `/api/v3` endpoint for GitHub Enterprise Server.
6. Run Connection Diagnostics.
7. Load repositories and branches, save defaults, and open Upload Center.
8. Select a folder or ZIP archive and click Upload and Commit.

The target repository must contain at least one commit. Initialize a new repository with a README before uploading.

== Recommended token permissions ==

* Metadata: read, for repository discovery.
* Contents: read and write, for commits and branch updates.
* Workflows: read and write, only when publishing .github/workflows files.

== wp-config.php constants ==

`define( 'GITHUBUPLOAD_TOKEN', 'github_pat_REPLACE_ME' );`

`define( 'GITHUBUPLOAD_API_ROOT', 'https://api.github.com' );`

`define( 'GITHUBUPLOAD_API_VERSION', '2026-03-10' );`

A token constant overrides the token stored in the WordPress database.

== Commit templates ==

Available variables are `{files}`, `{site}`, `{date}`, `{time}`, `{user}`, `{repository}`, and `{branch}`.

== Limits ==

GitHubUpload defaults to 500 files, 100 MB total, and 95 MB per file. Hosting limits such as `post_max_size`, `upload_max_filesize`, `max_file_uploads`, memory limits, and request timeouts may be lower.

== Changelog ==

= 2.0.0 =
* Added a full API Settings interface.
* Added GitHub Enterprise Server endpoints.
* Added API version, timeout, retries, and SSL settings.
* Added repository and branch discovery.
* Added rate-limit and permission diagnostics.
* Added wp-config.php credential and endpoint constants.
* Upgraded token encryption and retained v1 token migration support.
* Added sensitive-file and workflow-file protection.
* Added wildcard exclusions and configurable upload limits.
* Added commit message templates and optional author identity.
* Expanded the dashboard and responsive administration interface.

= 1.0.0 =
* Initial release.
