# API Setup

## GitHub.com

Use these values in **GitHubUpload → API Settings**:

- API URL: `https://api.github.com`
- API version: `2026-03-10`
- SSL verification: enabled
- Timeout: 90 seconds
- Retries: 1

Create a fine-grained personal access token limited to the repositories that WordPress needs to publish.

Recommended repository permissions:

- Metadata: Read
- Contents: Read and write
- Workflows: Read and write only when workflow files must be uploaded

After saving the token, click **Run Connection Diagnostics**, then **Load Repositories**.

## GitHub Enterprise Server

Use the Enterprise REST API root rather than the normal website URL:

```text
https://github.company.com/api/v3
```

Older Enterprise installations may need the `2022-11-28` API version. Keep SSL verification enabled and install the organization certificate chain on the WordPress server when a private certificate authority is used.

## wp-config.php

Production credentials can be kept out of the WordPress options table:

```php
define( 'GITHUBUPLOAD_TOKEN', 'github_pat_REPLACE_ME' );
define( 'GITHUBUPLOAD_API_ROOT', 'https://api.github.com' );
define( 'GITHUBUPLOAD_API_VERSION', '2026-03-10' );
```

Place constants before the `/* That's all, stop editing! */` line.
