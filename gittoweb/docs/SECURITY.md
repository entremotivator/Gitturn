# Security Guide

GitHubUpload is restricted to users with the `manage_options` capability by default. Every AJAX operation validates a WordPress nonce.

## Token handling

- The saved token is never returned to browser JavaScript.
- OpenSSL installations use AES-256-GCM encryption tied to WordPress security keys.
- A `GITHUBUPLOAD_TOKEN` constant overrides the database token.
- Use one fine-grained token per site or environment.
- Limit token repository access and expiration.
- Rotate a token immediately when it may have been exposed.

## Protected files

Sensitive-file protection blocks the operation when a configured path is detected. Default patterns include environment files, `wp-config.php`, private keys, package-manager authentication files, and common SSH identities.

Add organization-specific secret names to the pattern list. Wildcards are supported.

## Workflow files

Files under `.github/workflows/` are disabled by default. Enabling them requires deliberate confirmation in Security Settings, and GitHub may require a token with Workflows write permission.

## Server security

- Serve WordPress administration over HTTPS.
- Keep WordPress and PHP patched.
- Keep SSL verification enabled.
- Restrict administrator accounts.
- Review upload history after deployment activity.
- Keep PHP upload and memory limits as low as practical.
