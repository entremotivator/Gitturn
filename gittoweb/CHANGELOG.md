# Changelog

## 2.0.0

- Added GitHub.com and GitHub Enterprise API configuration.
- Added REST API version selection for `2026-03-10` and `2022-11-28`.
- Added repository and branch discovery.
- Added connection, permission, branch, rate-limit, and request-ID diagnostics.
- Added configurable timeouts, retries, repository visibility, and SSL verification.
- Added `GITHUBUPLOAD_TOKEN`, `GITHUBUPLOAD_API_ROOT`, and `GITHUBUPLOAD_API_VERSION` constant support.
- Replaced token storage with AES-256-GCM when OpenSSL is available.
- Added backwards-compatible decoding for v1 credentials.
- Added sensitive-file blocking and explicit workflow-file permission controls.
- Added wildcard exclusion patterns.
- Added total and per-file upload limits.
- Added commit message variables and optional commit author details.
- Added Enterprise-aware commit links.
- Expanded the responsive administration experience.

## 1.0.0

- Initial folder and ZIP uploader.
