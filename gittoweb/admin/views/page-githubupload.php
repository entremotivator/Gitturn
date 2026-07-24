<?php
if ( ! defined( 'ABSPATH' ) ) {
    exit;
}
?>
<div class="wrap githubupload-wrap">
    <div class="githubupload-hero">
        <div>
            <span class="githubupload-eyebrow"><?php esc_html_e( 'WordPress → GitHub API', 'githubupload' ); ?></span>
            <h1><?php esc_html_e( 'GitHubUpload', 'githubupload' ); ?></h1>
            <p><?php esc_html_e( 'Upload complete folders or ZIP projects to GitHub.com or GitHub Enterprise, preserve directory paths, and publish every upload as one atomic commit.', 'githubupload' ); ?></p>
            <div class="githubupload-hero-tags">
                <span><?php esc_html_e( 'Repository discovery', 'githubupload' ); ?></span>
                <span><?php esc_html_e( 'Branch controls', 'githubupload' ); ?></span>
                <span><?php esc_html_e( 'Encrypted credentials', 'githubupload' ); ?></span>
                <span><?php esc_html_e( 'Secret-file protection', 'githubupload' ); ?></span>
            </div>
        </div>
        <div class="githubupload-hero-badge">
            <span class="dashicons dashicons-cloud-upload"></span>
            <strong>v<?php echo esc_html( GITHUBUPLOAD_VERSION ); ?></strong>
            <small><?php esc_html_e( 'API Upload Center', 'githubupload' ); ?></small>
        </div>
    </div>

    <div id="githubupload-notice" class="githubupload-notice" hidden></div>

    <nav class="githubupload-tabs" aria-label="<?php esc_attr_e( 'GitHubUpload sections', 'githubupload' ); ?>">
        <button class="is-active" type="button" data-tab="upload"><span class="dashicons dashicons-upload"></span><?php esc_html_e( 'Upload Center', 'githubupload' ); ?></button>
        <button type="button" data-tab="api"><span class="dashicons dashicons-admin-network"></span><?php esc_html_e( 'API Settings', 'githubupload' ); ?></button>
        <button type="button" data-tab="security"><span class="dashicons dashicons-shield"></span><?php esc_html_e( 'Defaults & Security', 'githubupload' ); ?></button>
        <button type="button" data-tab="history"><span class="dashicons dashicons-backup"></span><?php esc_html_e( 'History', 'githubupload' ); ?></button>
    </nav>

    <datalist id="githubupload-repository-list"></datalist>
    <datalist id="githubupload-branch-list"></datalist>

    <section class="githubupload-tab is-active" data-panel="upload">
        <div class="githubupload-status-strip">
            <div><span class="dashicons dashicons-admin-network"></span><strong><?php esc_html_e( 'API', 'githubupload' ); ?></strong><small><?php echo esc_html( $settings['api_version'] ); ?></small></div>
            <div><span class="dashicons dashicons-lock"></span><strong><?php esc_html_e( 'Credential', 'githubupload' ); ?></strong><small><?php echo '' !== $this->token() ? esc_html__( 'Configured', 'githubupload' ) : esc_html__( 'Required', 'githubupload' ); ?></small></div>
            <div><span class="dashicons dashicons-media-archive"></span><strong><?php esc_html_e( 'Total limit', 'githubupload' ); ?></strong><small><?php echo esc_html( size_format( $this->max_total_bytes() ) ); ?></small></div>
            <div><span class="dashicons dashicons-editor-code"></span><strong><?php esc_html_e( 'Commit mode', 'githubupload' ); ?></strong><small><?php esc_html_e( 'Atomic Git tree', 'githubupload' ); ?></small></div>
        </div>

        <div class="githubupload-grid">
            <div class="githubupload-card githubupload-card-main">
                <div class="githubupload-card-head">
                    <div><span class="githubupload-step">1</span><h2><?php esc_html_e( 'Choose project content', 'githubupload' ); ?></h2></div>
                    <span id="githubupload-selection-summary" class="githubupload-pill"><?php esc_html_e( 'Nothing selected', 'githubupload' ); ?></span>
                </div>

                <div class="githubupload-source-switch">
                    <label class="is-active">
                        <input type="radio" name="githubupload_source" value="folder" checked>
                        <span class="dashicons dashicons-open-folder"></span>
                        <strong><?php esc_html_e( 'Folder upload', 'githubupload' ); ?></strong>
                        <small><?php esc_html_e( 'Preserves all nested paths', 'githubupload' ); ?></small>
                    </label>
                    <label>
                        <input type="radio" name="githubupload_source" value="zip">
                        <span class="dashicons dashicons-media-archive"></span>
                        <strong><?php esc_html_e( 'ZIP upload', 'githubupload' ); ?></strong>
                        <small><?php esc_html_e( 'Extract or store the ZIP', 'githubupload' ); ?></small>
                    </label>
                </div>

                <div id="githubupload-folder-zone" class="githubupload-dropzone">
                    <span class="dashicons dashicons-portfolio"></span>
                    <h3><?php esc_html_e( 'Select an entire folder', 'githubupload' ); ?></h3>
                    <p><?php esc_html_e( 'The browser sends the files with their relative paths. Files are processed temporarily and are never added to the WordPress Media Library.', 'githubupload' ); ?></p>
                    <label class="button button-primary button-hero"><?php esc_html_e( 'Browse Folder', 'githubupload' ); ?><input id="githubupload-folder-input" type="file" webkitdirectory directory multiple hidden></label>
                </div>

                <div id="githubupload-zip-zone" class="githubupload-dropzone" hidden>
                    <span class="dashicons dashicons-media-archive"></span>
                    <h3><?php esc_html_e( 'Select a ZIP project', 'githubupload' ); ?></h3>
                    <p><?php esc_html_e( 'Extract the archive into the repository or upload it as a single downloadable ZIP file according to your saved defaults.', 'githubupload' ); ?></p>
                    <label class="button button-primary button-hero"><?php esc_html_e( 'Browse ZIP', 'githubupload' ); ?><input id="githubupload-zip-input" type="file" accept=".zip,application/zip" hidden></label>
                </div>

                <div id="githubupload-file-preview" class="githubupload-file-preview" hidden>
                    <div class="githubupload-file-preview-head"><strong><?php esc_html_e( 'Upload manifest', 'githubupload' ); ?></strong><button id="githubupload-clear-selection" type="button" class="button-link-delete"><?php esc_html_e( 'Clear selection', 'githubupload' ); ?></button></div>
                    <div id="githubupload-file-list"></div>
                </div>
            </div>

            <aside class="githubupload-card githubupload-publish-card">
                <div class="githubupload-card-head"><div><span class="githubupload-step">2</span><h2><?php esc_html_e( 'Publish destination', 'githubupload' ); ?></h2></div></div>

                <label><span><?php esc_html_e( 'Repository', 'githubupload' ); ?></span>
                    <div class="githubupload-field-action"><input id="githubupload-repository" list="githubupload-repository-list" type="text" value="<?php echo esc_attr( $settings['repository'] ); ?>" placeholder="owner/repository" autocomplete="off"><button id="githubupload-load-repositories-upload" type="button" class="button" title="<?php esc_attr_e( 'Load repositories', 'githubupload' ); ?>"><span class="dashicons dashicons-update"></span></button></div>
                </label>
                <div class="githubupload-two-col">
                    <label><span><?php esc_html_e( 'Branch', 'githubupload' ); ?></span><div class="githubupload-field-action"><input id="githubupload-branch" list="githubupload-branch-list" type="text" value="<?php echo esc_attr( $settings['branch'] ); ?>" placeholder="main"><button id="githubupload-load-branches-upload" type="button" class="button"><span class="dashicons dashicons-update"></span></button></div></label>
                    <label><span><?php esc_html_e( 'Target folder', 'githubupload' ); ?></span><input id="githubupload-target-path" type="text" value="<?php echo esc_attr( $settings['target_path'] ); ?>" placeholder="optional/path"></label>
                </div>
                <label><span><?php esc_html_e( 'Commit message', 'githubupload' ); ?></span><input id="githubupload-commit-message" type="text" placeholder="<?php echo esc_attr( $settings['default_commit_message'] ); ?>"><small><?php esc_html_e( 'Leave blank to use the saved message template.', 'githubupload' ); ?></small></label>

                <label class="githubupload-check"><input id="githubupload-create-branch" type="checkbox" <?php checked( $settings['create_branch'] ); ?>><span><?php esc_html_e( 'Create the branch from the default branch when it does not exist', 'githubupload' ); ?></span></label>
                <label class="githubupload-check"><input id="githubupload-strip-root" type="checkbox" <?php checked( $settings['strip_root_folder'] ); ?>><span><?php esc_html_e( 'Remove the selected folder or ZIP root directory', 'githubupload' ); ?></span></label>

                <div id="githubupload-progress" class="githubupload-progress" hidden><div><span id="githubupload-progress-label"><?php esc_html_e( 'Preparing upload…', 'githubupload' ); ?></span><strong id="githubupload-progress-percent">0%</strong></div><progress id="githubupload-progress-bar" max="100" value="0"></progress></div>

                <button id="githubupload-start" type="button" class="button button-primary button-hero githubupload-start"><span class="dashicons dashicons-upload"></span><?php esc_html_e( 'Upload and Commit', 'githubupload' ); ?></button>
                <p class="description"><?php printf( esc_html__( 'Limits: %1$d files, %2$s total, and %3$s per file. PHP may impose lower limits.', 'githubupload' ), (int) $this->max_files(), esc_html( size_format( $this->max_total_bytes() ) ), esc_html( size_format( $this->max_single_bytes() ) ) ); ?></p>
            </aside>
        </div>
    </section>

    <section class="githubupload-tab" data-panel="api">
        <div class="githubupload-api-layout">
            <div class="githubupload-card">
                <div class="githubupload-card-head"><div><span class="githubupload-step">1</span><h2><?php esc_html_e( 'Authentication', 'githubupload' ); ?></h2></div><span id="githubupload-token-status" class="githubupload-pill <?php echo '' !== $this->token() ? 'is-success' : ''; ?>"><?php echo '' !== $this->token() ? esc_html__( 'Token configured', 'githubupload' ) : esc_html__( 'Token required', 'githubupload' ); ?></span></div>

                <?php if ( $token_constant ) : ?>
                    <div class="githubupload-config-banner"><span class="dashicons dashicons-lock"></span><div><strong><?php esc_html_e( 'wp-config.php token active', 'githubupload' ); ?></strong><p><?php esc_html_e( 'GITHUBUPLOAD_TOKEN overrides the database token. Remove or update that constant to change credentials.', 'githubupload' ); ?></p></div></div>
                <?php endif; ?>

                <label><span><?php esc_html_e( 'Personal access token', 'githubupload' ); ?></span><div class="githubupload-token-field"><input id="githubupload-token" type="password" value="" placeholder="<?php echo '' !== $this->token() ? esc_attr__( 'Saved token — enter a new token to replace it', 'githubupload' ) : 'github_pat_…'; ?>" <?php disabled( $token_constant ); ?>><button id="githubupload-toggle-token" type="button" class="button" <?php disabled( $token_constant ); ?>><?php esc_html_e( 'Show', 'githubupload' ); ?></button></div><small><?php esc_html_e( 'Recommended fine-grained permissions: Metadata read and Contents read/write. Add Workflows write only when uploading .github/workflows files.', 'githubupload' ); ?></small></label>
                <?php if ( $token_fingerprint ) : ?><p class="githubupload-fingerprint"><strong><?php esc_html_e( 'Credential fingerprint:', 'githubupload' ); ?></strong> <code><?php echo esc_html( $token_fingerprint ); ?></code></p><?php endif; ?>
                <label class="githubupload-check githubupload-danger-check"><input id="githubupload-clear-token" type="checkbox" <?php disabled( $token_constant ); ?>><span><?php esc_html_e( 'Remove the database-stored token when saving', 'githubupload' ); ?></span></label>
            </div>

            <div class="githubupload-card">
                <div class="githubupload-card-head"><div><span class="githubupload-step">2</span><h2><?php esc_html_e( 'API endpoint', 'githubupload' ); ?></h2></div></div>
                <label><span><?php esc_html_e( 'GitHub REST API URL', 'githubupload' ); ?></span><input id="githubupload-api-root" type="url" value="<?php echo esc_attr( $settings['api_root'] ); ?>" placeholder="https://api.github.com"><small><?php esc_html_e( 'For GitHub Enterprise Server, use a URL such as https://github.company.com/api/v3.', 'githubupload' ); ?></small></label>
                <div class="githubupload-two-col">
                    <label><span><?php esc_html_e( 'API version', 'githubupload' ); ?></span><select id="githubupload-api-version"><option value="2026-03-10" <?php selected( $settings['api_version'], '2026-03-10' ); ?>>2026-03-10</option><option value="2022-11-28" <?php selected( $settings['api_version'], '2022-11-28' ); ?>>2022-11-28</option></select></label>
                    <label><span><?php esc_html_e( 'Request timeout', 'githubupload' ); ?></span><input id="githubupload-request-timeout" type="number" min="15" max="300" value="<?php echo esc_attr( $settings['request_timeout'] ); ?>"><small><?php esc_html_e( 'Seconds per API request', 'githubupload' ); ?></small></label>
                </div>
                <div class="githubupload-two-col">
                    <label><span><?php esc_html_e( 'Automatic retries', 'githubupload' ); ?></span><select id="githubupload-retry-attempts"><?php for ( $retry = 0; $retry <= 3; $retry++ ) : ?><option value="<?php echo esc_attr( $retry ); ?>" <?php selected( (int) $settings['retry_attempts'], $retry ); ?>><?php echo esc_html( $retry ); ?></option><?php endfor; ?></select></label>
                    <label><span><?php esc_html_e( 'Repository filter', 'githubupload' ); ?></span><select id="githubupload-repository-visibility"><option value="all" <?php selected( $settings['repository_visibility'], 'all' ); ?>><?php esc_html_e( 'All accessible', 'githubupload' ); ?></option><option value="public" <?php selected( $settings['repository_visibility'], 'public' ); ?>><?php esc_html_e( 'Public only', 'githubupload' ); ?></option><option value="private" <?php selected( $settings['repository_visibility'], 'private' ); ?>><?php esc_html_e( 'Private only', 'githubupload' ); ?></option></select></label>
                </div>
                <label class="githubupload-check"><input id="githubupload-sslverify" type="checkbox" <?php checked( $settings['sslverify'] ); ?>><span><?php esc_html_e( 'Verify SSL certificates for every GitHub API request', 'githubupload' ); ?></span></label>
            </div>

            <div class="githubupload-card githubupload-card-wide">
                <div class="githubupload-card-head"><div><span class="githubupload-step">3</span><h2><?php esc_html_e( 'Repository explorer', 'githubupload' ); ?></h2></div><button id="githubupload-load-repositories" type="button" class="button"><span class="dashicons dashicons-update"></span><?php esc_html_e( 'Load Repositories', 'githubupload' ); ?></button></div>
                <div class="githubupload-three-col">
                    <label><span><?php esc_html_e( 'Default repository', 'githubupload' ); ?></span><input id="githubupload-settings-repository" list="githubupload-repository-list" type="text" value="<?php echo esc_attr( $settings['repository'] ); ?>" placeholder="owner/repository"></label>
                    <label><span><?php esc_html_e( 'Default branch', 'githubupload' ); ?></span><div class="githubupload-field-action"><input id="githubupload-settings-branch" list="githubupload-branch-list" type="text" value="<?php echo esc_attr( $settings['branch'] ); ?>" placeholder="main"><button id="githubupload-load-branches" type="button" class="button"><span class="dashicons dashicons-update"></span></button></div></label>
                    <label><span><?php esc_html_e( 'Default target folder', 'githubupload' ); ?></span><input id="githubupload-settings-target" type="text" value="<?php echo esc_attr( $settings['target_path'] ); ?>" placeholder="optional/path"></label>
                </div>
                <div id="githubupload-repository-result" class="githubupload-inline-result" hidden></div>
                <div class="githubupload-action-row"><button id="githubupload-test" type="button" class="button button-secondary"><span class="dashicons dashicons-admin-network"></span><?php esc_html_e( 'Run Connection Diagnostics', 'githubupload' ); ?></button><button id="githubupload-save-settings" type="button" class="button button-primary"><span class="dashicons dashicons-saved"></span><?php esc_html_e( 'Save All Settings', 'githubupload' ); ?></button></div>
            </div>

            <div id="githubupload-diagnostics" class="githubupload-card githubupload-card-wide" hidden>
                <div class="githubupload-card-head"><div><span class="githubupload-step is-blue">✓</span><h2><?php esc_html_e( 'Connection diagnostics', 'githubupload' ); ?></h2></div></div>
                <div id="githubupload-diagnostics-grid" class="githubupload-diagnostics-grid"></div>
            </div>
        </div>
    </section>

    <section class="githubupload-tab" data-panel="security">
        <div class="githubupload-grid githubupload-grid-settings">
            <div class="githubupload-card">
                <div class="githubupload-card-head"><div><span class="githubupload-step">1</span><h2><?php esc_html_e( 'Commit defaults', 'githubupload' ); ?></h2></div></div>
                <label><span><?php esc_html_e( 'Commit message template', 'githubupload' ); ?></span><input id="githubupload-default-message" type="text" value="<?php echo esc_attr( $settings['default_commit_message'] ); ?>"><small><?php esc_html_e( 'Variables: {files}, {site}, {date}, {time}, {user}, {repository}, and {branch}.', 'githubupload' ); ?></small></label>
                <div class="githubupload-two-col"><label><span><?php esc_html_e( 'Commit author name', 'githubupload' ); ?></span><input id="githubupload-author-name" type="text" value="<?php echo esc_attr( $settings['commit_author_name'] ); ?>" placeholder="Optional"></label><label><span><?php esc_html_e( 'Commit author email', 'githubupload' ); ?></span><input id="githubupload-author-email" type="email" value="<?php echo esc_attr( $settings['commit_author_email'] ); ?>" placeholder="Optional"></label></div>
                <fieldset><legend><?php esc_html_e( 'ZIP behavior', 'githubupload' ); ?></legend><label class="githubupload-radio"><input type="radio" name="githubupload_zip_mode" value="extract" <?php checked( $settings['zip_mode'], 'extract' ); ?>><span><strong><?php esc_html_e( 'Extract into repository', 'githubupload' ); ?></strong><small><?php esc_html_e( 'Each archive file becomes a Git blob in the commit.', 'githubupload' ); ?></small></span></label><label class="githubupload-radio"><input type="radio" name="githubupload_zip_mode" value="single" <?php checked( $settings['zip_mode'], 'single' ); ?>><span><strong><?php esc_html_e( 'Upload ZIP as one file', 'githubupload' ); ?></strong><small><?php esc_html_e( 'Preserves the original archive without extraction.', 'githubupload' ); ?></small></span></label></fieldset>
                <label><span><?php esc_html_e( 'General exclusion patterns', 'githubupload' ); ?></span><textarea id="githubupload-excludes" spellcheck="false"><?php echo esc_textarea( $settings['exclude_patterns'] ); ?></textarea><small><?php esc_html_e( 'One name, path, or wildcard per line. Examples: node_modules, *.log, build/**.', 'githubupload' ); ?></small></label>
            </div>

            <div class="githubupload-card">
                <div class="githubupload-card-head"><div><span class="githubupload-step">2</span><h2><?php esc_html_e( 'Protection and limits', 'githubupload' ); ?></h2></div></div>
                <label class="githubupload-check githubupload-security-check"><input id="githubupload-protect-sensitive" type="checkbox" <?php checked( $settings['protect_sensitive_files'] ); ?>><span><strong><?php esc_html_e( 'Block sensitive files', 'githubupload' ); ?></strong><small><?php esc_html_e( 'Stops the entire commit when a protected credential or secret file is found.', 'githubupload' ); ?></small></span></label>
                <label><span><?php esc_html_e( 'Sensitive-file patterns', 'githubupload' ); ?></span><textarea id="githubupload-sensitive-patterns" spellcheck="false"><?php echo esc_textarea( $settings['sensitive_patterns'] ); ?></textarea></label>
                <label class="githubupload-check githubupload-warning-check"><input id="githubupload-allow-workflows" type="checkbox" <?php checked( $settings['allow_workflow_files'] ); ?>><span><strong><?php esc_html_e( 'Allow .github/workflows files', 'githubupload' ); ?></strong><small><?php esc_html_e( 'Enable only when the token also has Workflows write permission.', 'githubupload' ); ?></small></span></label>
                <div class="githubupload-two-col"><label><span><?php esc_html_e( 'Maximum total upload', 'githubupload' ); ?></span><div class="githubupload-unit-field"><input id="githubupload-max-total" type="number" min="1" max="500" value="<?php echo esc_attr( $settings['max_total_mb'] ); ?>"><b>MB</b></div></label><label><span><?php esc_html_e( 'Maximum single file', 'githubupload' ); ?></span><div class="githubupload-unit-field"><input id="githubupload-max-single" type="number" min="1" max="100" value="<?php echo esc_attr( $settings['max_single_mb'] ); ?>"><b>MB</b></div></label></div>
                <label class="githubupload-check githubupload-danger-check"><input id="githubupload-delete-data" type="checkbox" <?php checked( $settings['delete_on_uninstall'] ); ?>><span><?php esc_html_e( 'Delete GitHubUpload settings and history when the plugin is uninstalled', 'githubupload' ); ?></span></label>
                <div class="githubupload-action-row"><button id="githubupload-save-security" type="button" class="button button-primary"><span class="dashicons dashicons-saved"></span><?php esc_html_e( 'Save All Settings', 'githubupload' ); ?></button></div>
            </div>
        </div>
    </section>

    <section class="githubupload-tab" data-panel="history">
        <div class="githubupload-card">
            <div class="githubupload-card-head"><div><span class="githubupload-step">✓</span><h2><?php esc_html_e( 'Upload and commit history', 'githubupload' ); ?></h2></div><?php if ( ! empty( $history ) ) : ?><button id="githubupload-clear-history" type="button" class="button button-secondary"><?php esc_html_e( 'Clear History', 'githubupload' ); ?></button><?php endif; ?></div>
            <div id="githubupload-history-wrap">
                <?php if ( empty( $history ) ) : ?>
                    <div class="githubupload-empty-state"><span class="dashicons dashicons-backup"></span><h3><?php esc_html_e( 'No uploads yet', 'githubupload' ); ?></h3><p><?php esc_html_e( 'Completed and failed GitHub operations will appear here.', 'githubupload' ); ?></p></div>
                <?php else : ?>
                    <div class="githubupload-history-table-wrap"><table class="widefat striped githubupload-history-table"><thead><tr><th><?php esc_html_e( 'Status', 'githubupload' ); ?></th><th><?php esc_html_e( 'Date', 'githubupload' ); ?></th><th><?php esc_html_e( 'Destination', 'githubupload' ); ?></th><th><?php esc_html_e( 'Files', 'githubupload' ); ?></th><th><?php esc_html_e( 'Size', 'githubupload' ); ?></th><th><?php esc_html_e( 'Commit / Result', 'githubupload' ); ?></th></tr></thead><tbody>
                    <?php foreach ( $history as $entry ) : ?><tr><td><span class="githubupload-status githubupload-status-<?php echo esc_attr( $entry['status'] ); ?>"><?php echo esc_html( $entry['status'] ); ?></span></td><td><?php echo esc_html( $entry['time'] ); ?></td><td><strong><?php echo esc_html( $entry['repository'] ); ?></strong><br><code><?php echo esc_html( $entry['branch'] ); ?></code></td><td><?php echo esc_html( number_format_i18n( (int) $entry['files'] ) ); ?></td><td><?php echo esc_html( size_format( (int) $entry['bytes'] ) ); ?></td><td><?php if ( ! empty( $entry['commit_url'] ) ) : ?><a href="<?php echo esc_url( $entry['commit_url'] ); ?>" target="_blank" rel="noopener noreferrer"><code><?php echo esc_html( substr( $entry['commit_sha'], 0, 9 ) ); ?></code></a><br><small><?php echo esc_html( $entry['message'] ); ?></small><?php else : ?><span class="githubupload-error-text"><?php echo esc_html( $entry['error'] ); ?></span><?php endif; ?></td></tr><?php endforeach; ?>
                    </tbody></table></div>
                <?php endif; ?>
            </div>
        </div>
    </section>
</div>
