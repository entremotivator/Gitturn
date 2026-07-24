<?php

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

final class GitHubUpload {
    const OPTION_SETTINGS = 'githubupload_settings';
    const OPTION_HISTORY  = 'githubupload_history';
    const NONCE_ACTION    = 'githubupload_admin';

    private static $instance;

    public static function instance() {
        if ( null === self::$instance ) {
            self::$instance = new self();
        }

        return self::$instance;
    }

    public static function activate() {
        $defaults = self::default_settings();
        $current  = get_option( self::OPTION_SETTINGS, array() );
        update_option( self::OPTION_SETTINGS, wp_parse_args( $current, $defaults ), false );
    }

    private function __construct() {
        add_action( 'admin_menu', array( $this, 'admin_menu' ) );
        add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_assets' ) );

        add_action( 'wp_ajax_githubupload_save_settings', array( $this, 'ajax_save_settings' ) );
        add_action( 'wp_ajax_githubupload_test_connection', array( $this, 'ajax_test_connection' ) );
        add_action( 'wp_ajax_githubupload_discover_repositories', array( $this, 'ajax_discover_repositories' ) );
        add_action( 'wp_ajax_githubupload_discover_branches', array( $this, 'ajax_discover_branches' ) );
        add_action( 'wp_ajax_githubupload_upload', array( $this, 'ajax_upload' ) );
        add_action( 'wp_ajax_githubupload_clear_history', array( $this, 'ajax_clear_history' ) );
    }

    public static function default_settings() {
        return array(
            'token'                   => '',
            'api_root'                => 'https://api.github.com',
            'api_version'             => '2026-03-10',
            'request_timeout'         => 90,
            'retry_attempts'          => 1,
            'sslverify'               => 1,
            'repository_visibility'   => 'all',
            'repository'              => '',
            'branch'                  => 'main',
            'target_path'             => '',
            'create_branch'           => 1,
            'strip_root_folder'       => 1,
            'zip_mode'                => 'extract',
            'default_commit_message'  => 'Upload {files} files from {site} on {date} at {time}',
            'commit_author_name'      => '',
            'commit_author_email'     => '',
            'exclude_patterns'        => ".git\n.git/**\nnode_modules\nnode_modules/**\nvendor\nvendor/**\n.DS_Store\n__MACOSX\nThumbs.db\n*.log",
            'protect_sensitive_files' => 1,
            'sensitive_patterns'      => ".env\n.env.*\nwp-config.php\n*.pem\n*.key\n*.p12\n*.pfx\nid_rsa\nid_ed25519\nauth.json\n.npmrc",
            'allow_workflow_files'    => 0,
            'max_total_mb'            => 100,
            'max_single_mb'           => 95,
            'delete_on_uninstall'     => 0,
        );
    }

    public function admin_menu() {
        add_menu_page(
            __( 'GitHubUpload', 'githubupload' ),
            __( 'GitHubUpload', 'githubupload' ),
            $this->capability(),
            'githubupload',
            array( $this, 'render_admin_page' ),
            'dashicons-cloud-upload',
            58
        );
    }

    public function enqueue_assets( $hook ) {
        if ( 'toplevel_page_githubupload' !== $hook ) {
            return;
        }

        wp_enqueue_style(
            'githubupload-admin',
            GITHUBUPLOAD_URL . 'assets/css/admin.css',
            array(),
            GITHUBUPLOAD_VERSION
        );

        wp_enqueue_script(
            'githubupload-admin',
            GITHUBUPLOAD_URL . 'assets/js/admin.js',
            array(),
            GITHUBUPLOAD_VERSION,
            true
        );

        wp_localize_script(
            'githubupload-admin',
            'GitHubUploadData',
            array(
                'ajaxUrl'       => admin_url( 'admin-ajax.php' ),
                'nonce'         => wp_create_nonce( self::NONCE_ACTION ),
                'maxFiles'      => $this->max_files(),
                'maxBytes'      => $this->max_total_bytes(),
                'maxSingleBytes'=> $this->max_single_bytes(),
                'tokenConstant' => defined( 'GITHUBUPLOAD_TOKEN' ),
                'hasSavedToken' => '' !== $this->token(),
                'strings'       => array(
                    'chooseFiles'     => __( 'Choose a folder or ZIP file first.', 'githubupload' ),
                    'uploading'       => __( 'Uploading files to WordPress…', 'githubupload' ),
                    'committing'      => __( 'Creating GitHub blobs and commit…', 'githubupload' ),
                    'saved'           => __( 'Settings saved.', 'githubupload' ),
                    'confirmClear'    => __( 'Clear all GitHubUpload history?', 'githubupload' ),
                    'tooManyFiles'    => __( 'The selected item contains more files than this site allows.', 'githubupload' ),
                    'tooLarge'        => __( 'The selected files exceed the configured total upload limit.', 'githubupload' ),
                    'singleTooLarge'  => __( 'At least one selected file exceeds the configured per-file limit.', 'githubupload' ),
                    'noRepositories'  => __( 'No repositories were returned for this token.', 'githubupload' ),
                    'noBranches'      => __( 'No branches were returned for this repository.', 'githubupload' ),
                    'serverError'     => __( 'The request failed. Check the browser console and WordPress/PHP upload limits.', 'githubupload' ),
                ),
            )
        );
    }

    public function render_admin_page() {
        if ( ! current_user_can( $this->capability() ) ) {
            wp_die( esc_html__( 'You do not have permission to use GitHubUpload.', 'githubupload' ) );
        }

        $settings          = $this->settings();
        $history           = get_option( self::OPTION_HISTORY, array() );
        $token_fingerprint = GitHubUpload_Crypto::fingerprint( $this->token() );
        $token_constant    = defined( 'GITHUBUPLOAD_TOKEN' );
        include GITHUBUPLOAD_DIR . 'admin/views/page-githubupload.php';
    }

    public function ajax_save_settings() {
        $this->guard_ajax();

        $existing = $this->settings();
        $token     = isset( $_POST['token'] ) ? trim( sanitize_text_field( wp_unslash( $_POST['token'] ) ) ) : '';
        $clear     = ! empty( $_POST['clear_token'] );

        if ( defined( 'GITHUBUPLOAD_TOKEN' ) ) {
            $stored_token = $existing['token'];
        } elseif ( $clear ) {
            $stored_token = '';
        } elseif ( '' !== $token ) {
            $stored_token = GitHubUpload_Crypto::encrypt( $token );
        } else {
            $stored_token = $existing['token'];
        }

        $settings = array(
            'token'                   => $stored_token,
            'api_root'                => $this->sanitize_api_root( isset( $_POST['api_root'] ) ? wp_unslash( $_POST['api_root'] ) : $existing['api_root'] ),
            'api_version'             => $this->sanitize_api_version( isset( $_POST['api_version'] ) ? wp_unslash( $_POST['api_version'] ) : $existing['api_version'] ),
            'request_timeout'         => $this->bounded_int( isset( $_POST['request_timeout'] ) ? $_POST['request_timeout'] : 90, 15, 300 ),
            'retry_attempts'          => $this->bounded_int( isset( $_POST['retry_attempts'] ) ? $_POST['retry_attempts'] : 1, 0, 3 ),
            'sslverify'               => ! empty( $_POST['sslverify'] ) ? 1 : 0,
            'repository_visibility'   => $this->sanitize_visibility( isset( $_POST['repository_visibility'] ) ? wp_unslash( $_POST['repository_visibility'] ) : 'all' ),
            'repository'              => $this->sanitize_repository( isset( $_POST['repository'] ) ? wp_unslash( $_POST['repository'] ) : '' ),
            'branch'                  => $this->sanitize_branch( isset( $_POST['branch'] ) ? wp_unslash( $_POST['branch'] ) : 'main' ),
            'target_path'             => $this->sanitize_repo_path( isset( $_POST['target_path'] ) ? wp_unslash( $_POST['target_path'] ) : '', true ),
            'create_branch'           => ! empty( $_POST['create_branch'] ) ? 1 : 0,
            'strip_root_folder'       => ! empty( $_POST['strip_root_folder'] ) ? 1 : 0,
            'zip_mode'                => isset( $_POST['zip_mode'] ) && 'single' === $_POST['zip_mode'] ? 'single' : 'extract',
            'default_commit_message'  => isset( $_POST['default_commit_message'] ) ? sanitize_text_field( wp_unslash( $_POST['default_commit_message'] ) ) : self::default_settings()['default_commit_message'],
            'commit_author_name'      => isset( $_POST['commit_author_name'] ) ? sanitize_text_field( wp_unslash( $_POST['commit_author_name'] ) ) : '',
            'commit_author_email'     => isset( $_POST['commit_author_email'] ) ? sanitize_email( wp_unslash( $_POST['commit_author_email'] ) ) : '',
            'exclude_patterns'        => isset( $_POST['exclude_patterns'] ) ? sanitize_textarea_field( wp_unslash( $_POST['exclude_patterns'] ) ) : '',
            'protect_sensitive_files' => ! empty( $_POST['protect_sensitive_files'] ) ? 1 : 0,
            'sensitive_patterns'      => isset( $_POST['sensitive_patterns'] ) ? sanitize_textarea_field( wp_unslash( $_POST['sensitive_patterns'] ) ) : '',
            'allow_workflow_files'    => ! empty( $_POST['allow_workflow_files'] ) ? 1 : 0,
            'max_total_mb'            => $this->bounded_int( isset( $_POST['max_total_mb'] ) ? $_POST['max_total_mb'] : 100, 1, 500 ),
            'max_single_mb'           => $this->bounded_int( isset( $_POST['max_single_mb'] ) ? $_POST['max_single_mb'] : 95, 1, 100 ),
            'delete_on_uninstall'     => ! empty( $_POST['delete_on_uninstall'] ) ? 1 : 0,
        );

        if ( '' === $settings['api_root'] ) {
            wp_send_json_error( array( 'message' => __( 'Enter a valid HTTPS GitHub API URL.', 'githubupload' ) ), 400 );
        }
        if ( '' === $settings['branch'] ) {
            $settings['branch'] = 'main';
        }
        if ( '' === $settings['default_commit_message'] ) {
            $settings['default_commit_message'] = self::default_settings()['default_commit_message'];
        }
        if ( $settings['max_single_mb'] > $settings['max_total_mb'] ) {
            $settings['max_single_mb'] = min( 100, $settings['max_total_mb'] );
        }

        update_option( self::OPTION_SETTINGS, $settings, false );

        wp_send_json_success(
            array(
                'message'       => __( 'API, upload, and security settings saved.', 'githubupload' ),
                'hasSavedToken' => defined( 'GITHUBUPLOAD_TOKEN' ) || '' !== $this->token_from_settings( $settings ),
                'maxBytes'      => (int) $settings['max_total_mb'] * MB_IN_BYTES,
                'maxSingleBytes'=> (int) $settings['max_single_mb'] * MB_IN_BYTES,
            )
        );
    }

    public function ajax_test_connection() {
        $this->guard_ajax();

        $settings   = $this->settings_from_request();
        $token      = $this->request_token_or_saved();
        $repository = $settings['repository'];
        $branch     = $settings['branch'];
        $api        = $this->api( $token, $settings );
        $user       = $api->get_authenticated_user();

        if ( is_wp_error( $user ) ) {
            $this->send_api_error( $user );
        }

        $repo          = array();
        $branch_exists = null;

        if ( '' !== $repository ) {
            $repo = $api->get_repository( $repository );
            if ( is_wp_error( $repo ) ) {
                $this->send_api_error( $repo );
            }

            if ( '' !== $branch ) {
                $ref = $api->get_ref( $repository, $branch );
                if ( is_wp_error( $ref ) ) {
                    $ref_data = $ref->get_error_data();
                    $branch_exists = is_array( $ref_data ) && isset( $ref_data['status'] ) && 404 === (int) $ref_data['status'] ? false : null;
                } else {
                    $branch_exists = true;
                }
            }
        }

        $rate = $api->get_rate_limit();
        $core = ! is_wp_error( $rate ) && ! empty( $rate['resources']['core'] ) ? $rate['resources']['core'] : array();
        $meta = $api->get_last_meta();

        wp_send_json_success(
            array(
                'message'       => '' === $repository
                    ? sprintf( __( 'Connected successfully as @%s.', 'githubupload' ), isset( $user['login'] ) ? $user['login'] : 'unknown' )
                    : sprintf( __( 'Connected as @%1$s. Repository %2$s is accessible.', 'githubupload' ), isset( $user['login'] ) ? $user['login'] : 'unknown', $repository ),
                'login'         => isset( $user['login'] ) ? $user['login'] : '',
                'repository'    => $repository,
                'private'       => ! empty( $repo['private'] ),
                'defaultBranch' => isset( $repo['default_branch'] ) ? $repo['default_branch'] : '',
                'branchExists'  => $branch_exists,
                'branch'        => $branch,
                'canPush'       => isset( $repo['permissions']['push'] ) ? (bool) $repo['permissions']['push'] : null,
                'archived'      => ! empty( $repo['archived'] ),
                'rateLimit'     => array(
                    'limit'     => isset( $core['limit'] ) ? (int) $core['limit'] : 0,
                    'remaining' => isset( $core['remaining'] ) ? (int) $core['remaining'] : 0,
                    'reset'     => isset( $core['reset'] ) ? (int) $core['reset'] : 0,
                ),
                'apiRoot'       => $settings['api_root'],
                'apiVersion'    => $settings['api_version'],
                'requestId'     => isset( $meta['request_id'] ) ? $meta['request_id'] : '',
            )
        );
    }

    public function ajax_discover_repositories() {
        $this->guard_ajax();
        $settings = $this->settings_from_request();
        $api = $this->api( $this->request_token_or_saved(), $settings );
        $repos = $api->list_repositories( $settings['repository_visibility'], 5 );
        if ( is_wp_error( $repos ) ) {
            $this->send_api_error( $repos );
        }
        $items = array();
        foreach ( $repos as $repo ) {
            if ( empty( $repo['full_name'] ) ) {
                continue;
            }
            $items[] = array(
                'fullName'      => $repo['full_name'],
                'private'       => ! empty( $repo['private'] ),
                'archived'      => ! empty( $repo['archived'] ),
                'defaultBranch' => isset( $repo['default_branch'] ) ? $repo['default_branch'] : 'main',
                'canPush'       => isset( $repo['permissions']['push'] ) ? (bool) $repo['permissions']['push'] : null,
            );
        }
        wp_send_json_success( array( 'repositories' => $items, 'message' => sprintf( _n( '%d repository loaded.', '%d repositories loaded.', count( $items ), 'githubupload' ), count( $items ) ) ) );
    }

    public function ajax_discover_branches() {
        $this->guard_ajax();
        $settings = $this->settings_from_request();
        if ( '' === $settings['repository'] ) {
            wp_send_json_error( array( 'message' => __( 'Enter a repository before loading branches.', 'githubupload' ) ), 400 );
        }
        $api = $this->api( $this->request_token_or_saved(), $settings );
        $branches = $api->list_branches( $settings['repository'], 5 );
        if ( is_wp_error( $branches ) ) {
            $this->send_api_error( $branches );
        }
        $items = array();
        foreach ( $branches as $branch ) {
            if ( ! empty( $branch['name'] ) ) {
                $items[] = array( 'name' => $branch['name'], 'protected' => ! empty( $branch['protected'] ) );
            }
        }
        wp_send_json_success( array( 'branches' => $items, 'message' => sprintf( _n( '%d branch loaded.', '%d branches loaded.', count( $items ), 'githubupload' ), count( $items ) ) ) );
    }

    public function ajax_upload() {
        $this->guard_ajax();

        @set_time_limit( 0 ); // phpcs:ignore WordPress.PHP.NoSilencedErrors.Discouraged

        $settings   = $this->settings_from_request();
        $token      = $this->request_token_or_saved();
        $repository = $settings['repository'];
        $branch     = $settings['branch'];
        $message    = isset( $_POST['commit_message'] ) ? sanitize_text_field( wp_unslash( $_POST['commit_message'] ) ) : '';

        if ( '' === $repository || '' === $branch ) {
            wp_send_json_error( array( 'message' => __( 'Repository and branch are required.', 'githubupload' ) ), 400 );
        }

        if ( empty( $_FILES['files'] ) || empty( $_FILES['files']['tmp_name'] ) ) {
            wp_send_json_error(
                array( 'message' => __( 'No upload reached WordPress. Check post_max_size, upload_max_filesize, and max_file_uploads in PHP.', 'githubupload' ) ),
                400
            );
        }

        $prepared = $this->prepare_uploaded_files( $settings );

        if ( is_wp_error( $prepared ) ) {
            wp_send_json_error( array( 'message' => $prepared->get_error_message() ), 400 );
        }

        if ( empty( $prepared['files'] ) ) {
            wp_send_json_error( array( 'message' => __( 'No eligible files remained after exclusions and security checks.', 'githubupload' ) ), 400 );
        }
        if ( '' === $message ) {
            $message = $this->render_commit_message( $settings['default_commit_message'], $repository, $branch, count( $prepared['files'] ) );
        }

        $api  = $this->api( $token, $settings );
        $repo = $api->get_repository( $repository );

        if ( is_wp_error( $repo ) ) {
            $this->log_failure( $repository, $branch, $prepared, $repo->get_error_message() );
            $this->send_api_error( $repo );
        }
        if ( ! empty( $repo['archived'] ) || ! empty( $repo['disabled'] ) ) {
            wp_send_json_error( array( 'message' => __( 'This repository is archived or disabled.', 'githubupload' ) ), 409 );
        }
        if ( isset( $repo['permissions']['push'] ) && ! $repo['permissions']['push'] ) {
            wp_send_json_error( array( 'message' => __( 'The token can read this repository but does not have push permission.', 'githubupload' ) ), 403 );
        }

        $ref = $api->get_ref( $repository, $branch );

        if ( is_wp_error( $ref ) ) {
            $ref_data   = $ref->get_error_data();
            $ref_status = is_array( $ref_data ) && isset( $ref_data['status'] ) ? (int) $ref_data['status'] : 500;

            if ( 404 !== $ref_status || empty( $settings['create_branch'] ) ) {
                $this->log_failure( $repository, $branch, $prepared, $ref->get_error_message() );
                $this->send_api_error( $ref );
            }

            $default_branch = ! empty( $repo['default_branch'] ) ? $repo['default_branch'] : 'main';
            $base_ref       = $api->get_ref( $repository, $default_branch );

            if ( is_wp_error( $base_ref ) || empty( $base_ref['object']['sha'] ) ) {
                $message_empty = __( 'Could not resolve the repository default branch. The repository may be empty; initialize it on GitHub with a README, then try again.', 'githubupload' );
                $error = new WP_Error( 'githubupload_no_base_ref', $message_empty, array( 'status' => 409 ) );
                $this->log_failure( $repository, $branch, $prepared, $message_empty );
                $this->send_api_error( $error );
            }

            $created_ref = $api->create_ref( $repository, $branch, $base_ref['object']['sha'] );

            if ( is_wp_error( $created_ref ) ) {
                $this->log_failure( $repository, $branch, $prepared, $created_ref->get_error_message() );
                $this->send_api_error( $created_ref );
            }

            $ref = $created_ref;
        }

        $parent_sha = isset( $ref['object']['sha'] ) ? $ref['object']['sha'] : '';

        if ( '' === $parent_sha ) {
            $error_message = __( 'GitHub did not return the branch commit SHA.', 'githubupload' );
            $this->log_failure( $repository, $branch, $prepared, $error_message );
            wp_send_json_error( array( 'message' => $error_message ), 500 );
        }

        $parent_commit = $api->get_commit( $repository, $parent_sha );

        if ( is_wp_error( $parent_commit ) || empty( $parent_commit['tree']['sha'] ) ) {
            $error = is_wp_error( $parent_commit ) ? $parent_commit : new WP_Error( 'githubupload_no_tree', __( 'Could not resolve the parent Git tree.', 'githubupload' ) );
            $this->log_failure( $repository, $branch, $prepared, $error->get_error_message() );
            $this->send_api_error( $error );
        }

        $entries = array();

        foreach ( $prepared['files'] as $file ) {
            $content = call_user_func( $file['reader'] );

            if ( is_wp_error( $content ) ) {
                $this->log_failure( $repository, $branch, $prepared, $content->get_error_message() );
                wp_send_json_error( array( 'message' => $content->get_error_message() ), 400 );
            }

            $blob = $api->create_blob( $repository, $content );
            unset( $content );

            if ( is_wp_error( $blob ) || empty( $blob['sha'] ) ) {
                $error = is_wp_error( $blob ) ? $blob : new WP_Error( 'githubupload_no_blob_sha', __( 'GitHub did not return a blob SHA.', 'githubupload' ) );
                $this->log_failure( $repository, $branch, $prepared, $error->get_error_message() );
                $this->send_api_error( $error );
            }

            $entries[] = array(
                'path' => $file['path'],
                'mode' => '100644',
                'type' => 'blob',
                'sha'  => $blob['sha'],
            );
        }

        $tree = $api->create_tree( $repository, $parent_commit['tree']['sha'], $entries );

        if ( is_wp_error( $tree ) || empty( $tree['sha'] ) ) {
            $error = is_wp_error( $tree ) ? $tree : new WP_Error( 'githubupload_no_tree_sha', __( 'GitHub did not return the new tree SHA.', 'githubupload' ) );
            $this->log_failure( $repository, $branch, $prepared, $error->get_error_message() );
            $this->send_api_error( $error );
        }

        $commit = $api->create_commit( $repository, $message, $tree['sha'], $parent_sha, array(
            'name'  => $settings['commit_author_name'],
            'email' => $settings['commit_author_email'],
        ) );

        if ( is_wp_error( $commit ) || empty( $commit['sha'] ) ) {
            $error = is_wp_error( $commit ) ? $commit : new WP_Error( 'githubupload_no_commit_sha', __( 'GitHub did not return the commit SHA.', 'githubupload' ) );
            $this->log_failure( $repository, $branch, $prepared, $error->get_error_message() );
            $this->send_api_error( $error );
        }

        $updated = $api->update_ref( $repository, $branch, $commit['sha'] );

        if ( is_wp_error( $updated ) ) {
            $this->log_failure( $repository, $branch, $prepared, $updated->get_error_message() );
            $this->send_api_error( $updated );
        }

        $commit_url = $this->github_web_root( $settings['api_root'] ) . '/' . $repository . '/commit/' . rawurlencode( $commit['sha'] );

        $this->add_history(
            array(
                'status'      => 'success',
                'repository'  => $repository,
                'branch'      => $branch,
                'files'       => count( $prepared['files'] ),
                'bytes'       => $prepared['total_bytes'],
                'commit_sha'  => $commit['sha'],
                'commit_url'  => $commit_url,
                'message'     => $message,
                'error'       => '',
            )
        );

        wp_send_json_success(
            array(
                'message'     => sprintf(
                    /* translators: %d: number of files */
                    _n( '%d file committed to GitHub.', '%d files committed to GitHub.', count( $prepared['files'] ), 'githubupload' ),
                    count( $prepared['files'] )
                ),
                'files'       => count( $prepared['files'] ),
                'bytes'       => $prepared['total_bytes'],
                'commitSha'   => $commit['sha'],
                'commitUrl'   => $commit_url,
                'repository'  => $repository,
                'branch'      => $branch,
            )
        );
    }

    public function ajax_clear_history() {
        $this->guard_ajax();
        delete_option( self::OPTION_HISTORY );
        wp_send_json_success( array( 'message' => __( 'History cleared.', 'githubupload' ) ) );
    }

    private function prepare_uploaded_files( array $settings ) {
        $files         = $_FILES['files']; // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized
        $tmp_names     = is_array( $files['tmp_name'] ) ? $files['tmp_name'] : array( $files['tmp_name'] );
        $names         = is_array( $files['name'] ) ? $files['name'] : array( $files['name'] );
        $sizes         = is_array( $files['size'] ) ? $files['size'] : array( $files['size'] );
        $errors        = is_array( $files['error'] ) ? $files['error'] : array( $files['error'] );
        $posted_paths  = isset( $_POST['file_paths'] ) ? (array) wp_unslash( $_POST['file_paths'] ) : array();
        $source_type   = isset( $_POST['source_type'] ) && 'zip' === $_POST['source_type'] ? 'zip' : 'folder';
        $target_path   = $settings['target_path'];
        $prepared      = array();
        $total_bytes   = 0;

        if ( 'zip' === $source_type ) {
            if ( count( $tmp_names ) !== 1 || UPLOAD_ERR_OK !== (int) $errors[0] ) {
                return new WP_Error( 'githubupload_zip_upload_error', $this->upload_error_message( isset( $errors[0] ) ? (int) $errors[0] : UPLOAD_ERR_NO_FILE ) );
            }

            $zip_name = sanitize_file_name( $names[0] );
            if ( 'zip' !== strtolower( pathinfo( $zip_name, PATHINFO_EXTENSION ) ) ) {
                return new WP_Error( 'githubupload_not_zip', __( 'The ZIP upload must use a .zip file extension.', 'githubupload' ) );
            }

            if ( 'single' === $settings['zip_mode'] ) {
                $path = $this->join_repo_path( $target_path, $zip_name );
                $size = (int) $sizes[0];
                $limit_check = $this->validate_limits( 1, $size, $settings );
                if ( is_wp_error( $limit_check ) ) {
                    return $limit_check;
                }
                if ( $size > $this->max_single_bytes_for_settings( $settings ) ) {
                    return new WP_Error( 'githubupload_single_too_large', sprintf( __( 'The ZIP file is %1$s; the per-file limit is %2$s.', 'githubupload' ), size_format( $size ), size_format( $this->max_single_bytes_for_settings( $settings ) ) ) );
                }
                $tmp = $tmp_names[0];
                $prepared[] = array(
                    'path'   => $path,
                    'size'   => $size,
                    'reader' => static function() use ( $tmp ) {
                        $content = file_get_contents( $tmp ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents
                        return false === $content ? new WP_Error( 'githubupload_read_failed', __( 'Could not read the uploaded ZIP file.', 'githubupload' ) ) : $content;
                    },
                );
                $total_bytes = $size;
            } else {
                if ( ! class_exists( 'ZipArchive' ) ) {
                    return new WP_Error( 'githubupload_ziparchive_missing', __( 'PHP ZipArchive is required to extract ZIP uploads.', 'githubupload' ) );
                }

                $zip = new ZipArchive();
                if ( true !== $zip->open( $tmp_names[0] ) ) {
                    return new WP_Error( 'githubupload_zip_open_failed', __( 'The ZIP archive could not be opened.', 'githubupload' ) );
                }

                $common_root = ! empty( $settings['strip_root_folder'] ) ? $this->zip_common_root( $zip ) : '';

                for ( $i = 0; $i < $zip->numFiles; $i++ ) {
                    $stat = $zip->statIndex( $i );
                    if ( false === $stat || empty( $stat['name'] ) || '/' === substr( $stat['name'], -1 ) ) {
                        continue;
                    }

                    $raw_path = str_replace( '\\', '/', $stat['name'] );
                    if ( '' !== $common_root && 0 === strpos( $raw_path, $common_root ) ) {
                        $raw_path = substr( $raw_path, strlen( $common_root ) );
                    }

                    $relative = $this->sanitize_repo_path( $raw_path, false );
                    if ( '' === $relative || $this->is_excluded( $relative, $settings['exclude_patterns'] ) ) {
                        continue;
                    }
                    $security = $this->validate_repo_file_path( $this->join_repo_path( $target_path, $relative ), $settings );
                    if ( is_wp_error( $security ) ) {
                        $zip->close();
                        return $security;
                    }

                    $size = isset( $stat['size'] ) ? (int) $stat['size'] : 0;
                    if ( $size > $this->max_single_bytes_for_settings( $settings ) ) {
                        $zip->close();
                        return new WP_Error( 'githubupload_single_too_large', sprintf( __( 'The file %1$s is %2$s; the per-file limit is %3$s.', 'githubupload' ), $relative, size_format( $size ), size_format( $this->max_single_bytes_for_settings( $settings ) ) ) );
                    }
                    $path = $this->join_repo_path( $target_path, $relative );
                    $zip_index = $i;
                    $zip_file  = $tmp_names[0];

                    $prepared[] = array(
                        'path'   => $path,
                        'size'   => $size,
                        'reader' => static function() use ( $zip_file, $zip_index ) {
                            $archive = new ZipArchive();
                            if ( true !== $archive->open( $zip_file ) ) {
                                return new WP_Error( 'githubupload_zip_reopen_failed', __( 'Could not reopen the ZIP archive.', 'githubupload' ) );
                            }
                            $content = $archive->getFromIndex( $zip_index );
                            $archive->close();
                            return false === $content ? new WP_Error( 'githubupload_zip_read_failed', __( 'Could not read a file from the ZIP archive.', 'githubupload' ) ) : $content;
                        },
                    );
                    $total_bytes += $size;
                    $limit_check = $this->validate_limits( count( $prepared ), $total_bytes, $settings );
                    if ( is_wp_error( $limit_check ) ) {
                        $zip->close();
                        return $limit_check;
                    }
                }

                $zip->close();
            }
        } else {
            $root = ! empty( $settings['strip_root_folder'] ) ? $this->common_browser_root( $posted_paths ) : '';

            foreach ( $tmp_names as $index => $tmp ) {
                $error = isset( $errors[ $index ] ) ? (int) $errors[ $index ] : UPLOAD_ERR_NO_FILE;
                if ( UPLOAD_ERR_OK !== $error ) {
                    return new WP_Error( 'githubupload_upload_error', $this->upload_error_message( $error ) );
                }

                $raw_path = isset( $posted_paths[ $index ] ) && '' !== $posted_paths[ $index ] ? $posted_paths[ $index ] : $names[ $index ];
                $raw_path = str_replace( '\\', '/', (string) $raw_path );
                if ( '' !== $root && 0 === strpos( $raw_path, $root ) ) {
                    $raw_path = substr( $raw_path, strlen( $root ) );
                }

                $relative = $this->sanitize_repo_path( $raw_path, false );
                if ( '' === $relative || $this->is_excluded( $relative, $settings['exclude_patterns'] ) ) {
                    continue;
                }
                $security = $this->validate_repo_file_path( $this->join_repo_path( $target_path, $relative ), $settings );
                if ( is_wp_error( $security ) ) {
                    return $security;
                }

                $size = isset( $sizes[ $index ] ) ? (int) $sizes[ $index ] : 0;
                if ( $size > $this->max_single_bytes_for_settings( $settings ) ) {
                    return new WP_Error( 'githubupload_single_too_large', sprintf( __( 'The file %1$s is %2$s; the per-file limit is %3$s.', 'githubupload' ), $relative, size_format( $size ), size_format( $this->max_single_bytes_for_settings( $settings ) ) ) );
                }
                $path = $this->join_repo_path( $target_path, $relative );
                $local_tmp = $tmp;

                $prepared[] = array(
                    'path'   => $path,
                    'size'   => $size,
                    'reader' => static function() use ( $local_tmp ) {
                        $content = file_get_contents( $local_tmp ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents
                        return false === $content ? new WP_Error( 'githubupload_read_failed', __( 'Could not read an uploaded file.', 'githubupload' ) ) : $content;
                    },
                );
                $total_bytes += $size;
                $limit_check = $this->validate_limits( count( $prepared ), $total_bytes, $settings );
                if ( is_wp_error( $limit_check ) ) {
                    return $limit_check;
                }
            }
        }

        $limit_check = $this->validate_limits( count( $prepared ), $total_bytes, $settings );
        if ( is_wp_error( $limit_check ) ) {
            return $limit_check;
        }

        $paths = array();
        foreach ( $prepared as $file ) {
            if ( isset( $paths[ $file['path'] ] ) ) {
                return new WP_Error( 'githubupload_duplicate_path', sprintf( __( 'Two uploaded files resolve to the same repository path: %s', 'githubupload' ), $file['path'] ) );
            }
            $paths[ $file['path'] ] = true;
        }

        return array(
            'files'       => $prepared,
            'total_bytes' => $total_bytes,
        );
    }

    private function validate_limits( $count, $bytes, array $settings = array() ) {
        if ( $count > $this->max_files() ) {
            return new WP_Error( 'githubupload_too_many_files', sprintf( __( 'This upload contains %1$d files; the current limit is %2$d.', 'githubupload' ), $count, $this->max_files() ) );
        }

        $max_total = empty( $settings ) ? $this->max_total_bytes() : max( 1024, (int) $settings['max_total_mb'] * MB_IN_BYTES );
        if ( $bytes > $max_total ) {
            return new WP_Error( 'githubupload_too_large', sprintf( __( 'This upload is %1$s; the current total limit is %2$s.', 'githubupload' ), size_format( $bytes ), size_format( $max_total ) ) );
        }

        return true;
    }

    private function zip_common_root( ZipArchive $zip ) {
        $root = null;

        for ( $i = 0; $i < $zip->numFiles; $i++ ) {
            $name = str_replace( '\\', '/', $zip->getNameIndex( $i ) );
            $name = ltrim( $name, '/' );
            if ( '' === $name || false === strpos( $name, '/' ) ) {
                return '';
            }
            $candidate = strstr( $name, '/', true ) . '/';
            if ( null === $root ) {
                $root = $candidate;
            } elseif ( $root !== $candidate ) {
                return '';
            }
        }

        return null === $root ? '' : $root;
    }

    private function common_browser_root( array $paths ) {
        $root = null;
        foreach ( $paths as $path ) {
            $path = str_replace( '\\', '/', (string) $path );
            if ( false === strpos( $path, '/' ) ) {
                return '';
            }
            $candidate = strstr( $path, '/', true ) . '/';
            if ( null === $root ) {
                $root = $candidate;
            } elseif ( $root !== $candidate ) {
                return '';
            }
        }
        return null === $root ? '' : $root;
    }

    private function is_excluded( $path, $patterns ) {
        $parts = array_filter( array_map( 'trim', preg_split( '/[\r\n,]+/', (string) $patterns ) ) );
        $segments = explode( '/', $path );

        foreach ( $parts as $pattern ) {
            $pattern = trim( str_replace( '\\', '/', $pattern ), '/' );
            if ( '' === $pattern ) {
                continue;
            }

            if ( $this->wildcard_match( $pattern, $path ) || $this->wildcard_match( $pattern, basename( $path ) ) ) {
                return true;
            }
            if ( false !== strpos( $pattern, '/' ) ) {
                if ( 0 === strpos( $path, $pattern . '/' ) || $path === $pattern || false !== strpos( $path, '/' . $pattern . '/' ) ) {
                    return true;
                }
            } elseif ( in_array( $pattern, $segments, true ) || basename( $path ) === $pattern ) {
                return true;
            }
        }

        return false;
    }

    private function sanitize_repository( $value ) {
        $value = trim( (string) $value );
        $value = preg_replace( '#^https?://github\.com/#i', '', $value );
        $value = preg_replace( '#\.git$#i', '', $value );
        $value = trim( $value, "/ \t\n\r\0\x0B" );

        if ( ! preg_match( '/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/', $value ) ) {
            return '';
        }

        return $value;
    }

    private function sanitize_branch( $value ) {
        $value = trim( (string) $value );
        $value = preg_replace( '/[^A-Za-z0-9._\/-]/', '-', $value );
        $value = preg_replace( '#/+#', '/', $value );
        return trim( $value, '/.' );
    }

    private function sanitize_repo_path( $value, $allow_empty ) {
        $value = str_replace( '\\', '/', (string) $value );
        $value = preg_replace( '#/+#', '/', $value );
        $value = ltrim( $value, '/' );

        $safe = array();
        foreach ( explode( '/', $value ) as $segment ) {
            $segment = trim( $segment );
            if ( '' === $segment || '.' === $segment ) {
                continue;
            }
            if ( '..' === $segment || false !== strpos( $segment, "\0" ) ) {
                return '';
            }
            $segment = preg_replace( '/[\x00-\x1F\x7F]/u', '', $segment );
            if ( '' !== $segment ) {
                $safe[] = $segment;
            }
        }

        $path = implode( '/', $safe );
        return '' === $path && ! $allow_empty ? '' : $path;
    }

    private function join_repo_path( $base, $relative ) {
        $base     = trim( (string) $base, '/' );
        $relative = trim( (string) $relative, '/' );
        return '' === $base ? $relative : $base . '/' . $relative;
    }

    private function settings_from_request() {
        $stored = $this->settings();

        return array(
            'token'                   => $stored['token'],
            'api_root'                => $this->sanitize_api_root( defined( 'GITHUBUPLOAD_API_ROOT' ) ? GITHUBUPLOAD_API_ROOT : ( isset( $_POST['api_root'] ) ? wp_unslash( $_POST['api_root'] ) : $stored['api_root'] ) ),
            'api_version'             => $this->sanitize_api_version( defined( 'GITHUBUPLOAD_API_VERSION' ) ? GITHUBUPLOAD_API_VERSION : ( isset( $_POST['api_version'] ) ? wp_unslash( $_POST['api_version'] ) : $stored['api_version'] ) ),
            'request_timeout'         => $this->bounded_int( isset( $_POST['request_timeout'] ) ? $_POST['request_timeout'] : $stored['request_timeout'], 15, 300 ),
            'retry_attempts'          => $this->bounded_int( isset( $_POST['retry_attempts'] ) ? $_POST['retry_attempts'] : $stored['retry_attempts'], 0, 3 ),
            'sslverify'               => isset( $_POST['sslverify'] ) ? ( ! empty( $_POST['sslverify'] ) ? 1 : 0 ) : (int) $stored['sslverify'],
            'repository_visibility'   => $this->sanitize_visibility( isset( $_POST['repository_visibility'] ) ? wp_unslash( $_POST['repository_visibility'] ) : $stored['repository_visibility'] ),
            'repository'              => $this->sanitize_repository( isset( $_POST['repository'] ) ? wp_unslash( $_POST['repository'] ) : $stored['repository'] ),
            'branch'                  => $this->sanitize_branch( isset( $_POST['branch'] ) ? wp_unslash( $_POST['branch'] ) : $stored['branch'] ),
            'target_path'             => $this->sanitize_repo_path( isset( $_POST['target_path'] ) ? wp_unslash( $_POST['target_path'] ) : $stored['target_path'], true ),
            'create_branch'           => isset( $_POST['create_branch'] ) ? ( ! empty( $_POST['create_branch'] ) ? 1 : 0 ) : (int) $stored['create_branch'],
            'strip_root_folder'       => isset( $_POST['strip_root_folder'] ) ? ( ! empty( $_POST['strip_root_folder'] ) ? 1 : 0 ) : (int) $stored['strip_root_folder'],
            'zip_mode'                => isset( $_POST['zip_mode'] ) && 'single' === $_POST['zip_mode'] ? 'single' : $stored['zip_mode'],
            'default_commit_message'  => isset( $_POST['default_commit_message'] ) ? sanitize_text_field( wp_unslash( $_POST['default_commit_message'] ) ) : $stored['default_commit_message'],
            'commit_author_name'      => isset( $_POST['commit_author_name'] ) ? sanitize_text_field( wp_unslash( $_POST['commit_author_name'] ) ) : $stored['commit_author_name'],
            'commit_author_email'     => isset( $_POST['commit_author_email'] ) ? sanitize_email( wp_unslash( $_POST['commit_author_email'] ) ) : $stored['commit_author_email'],
            'exclude_patterns'        => isset( $_POST['exclude_patterns'] ) ? sanitize_textarea_field( wp_unslash( $_POST['exclude_patterns'] ) ) : $stored['exclude_patterns'],
            'protect_sensitive_files' => isset( $_POST['protect_sensitive_files'] ) ? ( ! empty( $_POST['protect_sensitive_files'] ) ? 1 : 0 ) : (int) $stored['protect_sensitive_files'],
            'sensitive_patterns'      => isset( $_POST['sensitive_patterns'] ) ? sanitize_textarea_field( wp_unslash( $_POST['sensitive_patterns'] ) ) : $stored['sensitive_patterns'],
            'allow_workflow_files'    => isset( $_POST['allow_workflow_files'] ) ? ( ! empty( $_POST['allow_workflow_files'] ) ? 1 : 0 ) : (int) $stored['allow_workflow_files'],
            'max_total_mb'            => $this->bounded_int( isset( $_POST['max_total_mb'] ) ? $_POST['max_total_mb'] : $stored['max_total_mb'], 1, 500 ),
            'max_single_mb'           => $this->bounded_int( isset( $_POST['max_single_mb'] ) ? $_POST['max_single_mb'] : $stored['max_single_mb'], 1, 100 ),
            'delete_on_uninstall'     => (int) $stored['delete_on_uninstall'],
        );
    }

    private function settings() {
        return wp_parse_args( get_option( self::OPTION_SETTINGS, array() ), self::default_settings() );
    }

    private function token() {
        if ( defined( 'GITHUBUPLOAD_TOKEN' ) ) {
            return trim( (string) GITHUBUPLOAD_TOKEN );
        }
        return $this->token_from_settings( $this->settings() );
    }

    private function token_from_settings( array $settings ) {
        return GitHubUpload_Crypto::decrypt( isset( $settings['token'] ) ? $settings['token'] : '' );
    }

    private function request_token_or_saved() {
        if ( defined( 'GITHUBUPLOAD_TOKEN' ) ) {
            return trim( (string) GITHUBUPLOAD_TOKEN );
        }
        $token = isset( $_POST['token'] ) ? trim( sanitize_text_field( wp_unslash( $_POST['token'] ) ) ) : '';
        return '' !== $token ? $token : $this->token();
    }

    private function guard_ajax() {
        check_ajax_referer( self::NONCE_ACTION, 'nonce' );
        if ( ! current_user_can( $this->capability() ) ) {
            wp_send_json_error( array( 'message' => __( 'You do not have permission to perform this action.', 'githubupload' ) ), 403 );
        }
    }

    private function capability() {
        return apply_filters( 'githubupload_capability', 'manage_options' );
    }

    private function max_files() {
        return max( 1, (int) apply_filters( 'githubupload_max_files', 500 ) );
    }

    private function max_total_bytes() {
        $settings = $this->settings();
        $default = max( 1, (int) $settings['max_total_mb'] ) * MB_IN_BYTES;
        return max( 1024, (int) apply_filters( 'githubupload_max_total_bytes', $default ) );
    }

    private function max_single_bytes() {
        $settings = $this->settings();
        $default = max( 1, min( 100, (int) $settings['max_single_mb'] ) ) * MB_IN_BYTES;
        return max( 1024, (int) apply_filters( 'githubupload_max_single_bytes', $default ) );
    }

    private function max_single_bytes_for_settings( array $settings ) {
        $default = max( 1, min( 100, (int) $settings['max_single_mb'] ) ) * MB_IN_BYTES;
        return max( 1024, (int) apply_filters( 'githubupload_max_single_bytes', $default ) );
    }

    private function api( $token, array $settings ) {
        return new GitHubUpload_API(
            $token,
            array(
                'api_root'    => $settings['api_root'],
                'api_version' => $settings['api_version'],
                'timeout'     => $settings['request_timeout'],
                'retries'     => $settings['retry_attempts'],
                'sslverify'   => ! empty( $settings['sslverify'] ),
            )
        );
    }

    private function sanitize_api_root( $value ) {
        $value = trim( (string) $value );
        if ( preg_match( '#^https://github\.com/?$#i', $value ) ) {
            return 'https://api.github.com';
        }
        $value = untrailingslashit( esc_url_raw( $value, array( 'https' ) ) );
        return 0 === strpos( $value, 'https://' ) ? $value : '';
    }

    private function sanitize_api_version( $value ) {
        $value = trim( (string) $value );
        return preg_match( '/^\d{4}-\d{2}-\d{2}$/', $value ) ? $value : '2026-03-10';
    }

    private function sanitize_visibility( $value ) {
        return in_array( $value, array( 'all', 'public', 'private' ), true ) ? $value : 'all';
    }

    private function bounded_int( $value, $min, $max ) {
        return max( (int) $min, min( (int) $max, (int) $value ) );
    }


    private function github_web_root( $api_root ) {
        $api_root = untrailingslashit( (string) $api_root );
        if ( 'https://api.github.com' === $api_root ) {
            return 'https://github.com';
        }
        return preg_replace( '#/api/v3$#i', '', $api_root );
    }

    private function validate_repo_file_path( $path, array $settings ) {
        if ( empty( $settings['allow_workflow_files'] ) && 0 === strpos( $path, '.github/workflows/' ) ) {
            return new WP_Error( 'githubupload_workflow_blocked', __( 'A .github/workflows file was detected. Enable workflow uploads in Security Settings and grant the token Workflows: write permission.', 'githubupload' ) );
        }
        if ( ! empty( $settings['protect_sensitive_files'] ) && $this->is_excluded( $path, $settings['sensitive_patterns'] ) ) {
            return new WP_Error( 'githubupload_sensitive_file', sprintf( __( 'Sensitive-file protection blocked: %s', 'githubupload' ), $path ) );
        }
        return true;
    }

    private function wildcard_match( $pattern, $value ) {
        if ( false === strpos( $pattern, '*' ) && false === strpos( $pattern, '?' ) ) {
            return false;
        }
        $quoted = preg_quote( $pattern, '#' );
        $regex = '#^' . str_replace( array( '\*\*', '\*', '\?' ), array( '.*', '[^/]*', '.' ), $quoted ) . '$#i';
        return 1 === preg_match( $regex, $value );
    }

    private function render_commit_message( $template, $repository, $branch, $files ) {
        $user = wp_get_current_user();
        $replace = array(
            '{files}'      => (string) (int) $files,
            '{site}'       => wp_specialchars_decode( get_bloginfo( 'name' ), ENT_QUOTES ),
            '{date}'       => wp_date( 'Y-m-d' ),
            '{time}'       => wp_date( 'H:i:s T' ),
            '{user}'       => $user && $user->exists() ? $user->display_name : '',
            '{repository}' => $repository,
            '{branch}'     => $branch,
        );
        return sanitize_text_field( strtr( (string) $template, $replace ) );
    }

    private function upload_error_message( $code ) {
        $messages = array(
            UPLOAD_ERR_INI_SIZE   => __( 'A file exceeds upload_max_filesize.', 'githubupload' ),
            UPLOAD_ERR_FORM_SIZE  => __( 'A file exceeds the form upload limit.', 'githubupload' ),
            UPLOAD_ERR_PARTIAL    => __( 'A file was only partially uploaded.', 'githubupload' ),
            UPLOAD_ERR_NO_FILE    => __( 'No file was uploaded.', 'githubupload' ),
            UPLOAD_ERR_NO_TMP_DIR => __( 'The server has no temporary upload directory.', 'githubupload' ),
            UPLOAD_ERR_CANT_WRITE => __( 'The server could not write an uploaded file.', 'githubupload' ),
            UPLOAD_ERR_EXTENSION  => __( 'A PHP extension stopped the upload.', 'githubupload' ),
        );
        return isset( $messages[ $code ] ) ? $messages[ $code ] : __( 'Unknown upload error.', 'githubupload' );
    }

    private function send_api_error( WP_Error $error ) {
        $data   = $error->get_error_data();
        $status = is_array( $data ) && ! empty( $data['status'] ) ? (int) $data['status'] : 500;
        wp_send_json_error(
            array(
                'message' => $error->get_error_message(),
                'status'  => $status,
            ),
            $status >= 400 && $status < 600 ? $status : 500
        );
    }

    private function log_failure( $repository, $branch, array $prepared, $error ) {
        $this->add_history(
            array(
                'status'      => 'failed',
                'repository'  => $repository,
                'branch'      => $branch,
                'files'       => isset( $prepared['files'] ) ? count( $prepared['files'] ) : 0,
                'bytes'       => isset( $prepared['total_bytes'] ) ? $prepared['total_bytes'] : 0,
                'commit_sha'  => '',
                'commit_url'  => '',
                'message'     => '',
                'error'       => sanitize_text_field( $error ),
            )
        );
    }

    private function add_history( array $entry ) {
        $history = get_option( self::OPTION_HISTORY, array() );
        array_unshift(
            $history,
            wp_parse_args(
                $entry,
                array(
                    'time'       => current_time( 'mysql' ),
                    'user_id'    => get_current_user_id(),
                    'status'     => '',
                    'repository' => '',
                    'branch'     => '',
                    'files'      => 0,
                    'bytes'      => 0,
                    'commit_sha' => '',
                    'commit_url' => '',
                    'message'    => '',
                    'error'      => '',
                )
            )
        );
        update_option( self::OPTION_HISTORY, array_slice( $history, 0, 25 ), false );
    }
}
