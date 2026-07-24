# Troubleshooting

## Token rejected

Confirm the token is active, copied completely, not expired, and authorized for the selected repository. Run connection diagnostics before uploading.

## Repository is not listed

Confirm the token has Metadata read permission and access to that repository. Change the Repository Filter to **All accessible** and reload repositories.

## Repository is read-only

The diagnostics panel may show that the token can read but cannot push. Grant Contents read/write permission or choose a repository where the token has write access.

## Branch is missing

Enable **Create the branch from the default branch**. The repository must already contain at least one commit. Initialize an empty repository with a README first.

## Workflow upload rejected

Enable workflow files in Security Settings and grant the token Workflows write permission. Keep this permission disabled when it is not needed.

## Upload never reaches WordPress

Review these PHP settings:

- `upload_max_filesize`
- `post_max_size`
- `max_file_uploads`
- `memory_limit`
- `max_execution_time`

Folder uploads can exceed `max_file_uploads` even when their total byte size is small.

## API rate limit reached

Open Connection Diagnostics and review the remaining requests and reset time. A folder commit generally uses one blob request per file plus requests for the repository, branch, tree, commit, and reference.

## SSL error with GitHub Enterprise

Install the correct certificate authority chain on the WordPress server. Disabling SSL verification should only be a temporary diagnostic step.

## ZIP extraction unavailable

Install or enable the PHP `ZipArchive` extension, or select the option to upload the ZIP as one file.
