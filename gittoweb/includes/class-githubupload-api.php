<?php

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

/**
 * GitHub REST API client used by GitHubUpload.
 */
final class GitHubUpload_API {
    private $token;
    private $api_root;
    private $api_version;
    private $timeout;
    private $retries;
    private $sslverify;
    private $last_meta = array();

    public function __construct( $token, array $config = array() ) {
        $defaults = array(
            'api_root'    => 'https://api.github.com',
            'api_version' => '2026-03-10',
            'timeout'     => 90,
            'retries'     => 1,
            'sslverify'   => true,
        );
        $config = wp_parse_args( $config, $defaults );

        $this->token       = trim( (string) $token );
        $this->api_root    = untrailingslashit( (string) $config['api_root'] );
        $this->api_version = trim( (string) $config['api_version'] );
        $this->timeout     = max( 15, min( 300, (int) $config['timeout'] ) );
        $this->retries     = max( 0, min( 3, (int) $config['retries'] ) );
        $this->sslverify   = (bool) $config['sslverify'];
    }

    public function request( $method, $endpoint, $body = null, $timeout = null ) {
        if ( '' === $this->token ) {
            return new WP_Error( 'githubupload_missing_token', __( 'A GitHub access token is required.', 'githubupload' ), array( 'status' => 401 ) );
        }

        $url   = $this->api_root . '/' . ltrim( $endpoint, '/' );
        $parts = wp_parse_url( $url );
        if ( empty( $parts['host'] ) || empty( $parts['scheme'] ) || 'https' !== strtolower( $parts['scheme'] ) ) {
            return new WP_Error( 'githubupload_invalid_api_url', __( 'The configured GitHub API URL must be a valid HTTPS address.', 'githubupload' ), array( 'status' => 400 ) );
        }

        $args = array(
            'method'      => strtoupper( (string) $method ),
            'timeout'     => null === $timeout ? $this->timeout : max( 15, min( 300, (int) $timeout ) ),
            'redirection' => 3,
            'sslverify'   => $this->sslverify,
            'headers'     => array(
                'Accept'               => 'application/vnd.github+json',
                'Authorization'        => 'Bearer ' . $this->token,
                'X-GitHub-Api-Version' => $this->api_version,
                'User-Agent'           => 'GitHubUpload-WordPress/' . GITHUBUPLOAD_VERSION . '; ' . home_url( '/' ),
            ),
        );

        if ( null !== $body ) {
            $args['headers']['Content-Type'] = 'application/json; charset=utf-8';
            $args['body'] = wp_json_encode( $body, JSON_UNESCAPED_SLASHES );
        }

        $attempt  = 0;
        $response = null;

        do {
            $response = wp_remote_request( $url, $args );

            if ( is_wp_error( $response ) ) {
                if ( $attempt < $this->retries ) {
                    sleep( min( 2, $attempt + 1 ) );
                    $attempt++;
                    continue;
                }
                return $response;
            }

            $status = (int) wp_remote_retrieve_response_code( $response );
            if ( $attempt < $this->retries && $this->is_retryable_status( $status ) ) {
                $retry_after = (int) wp_remote_retrieve_header( $response, 'retry-after' );
                sleep( max( 1, min( 3, $retry_after ? $retry_after : $attempt + 1 ) ) );
                $attempt++;
                continue;
            }

            break;
        } while ( $attempt <= $this->retries );

        $status  = (int) wp_remote_retrieve_response_code( $response );
        $raw     = (string) wp_remote_retrieve_body( $response );
        $decoded = '' === $raw ? array() : json_decode( $raw, true );
        $headers = wp_remote_retrieve_headers( $response );

        $this->last_meta = array(
            'status'               => $status,
            'rate_limit'           => (int) wp_remote_retrieve_header( $response, 'x-ratelimit-limit' ),
            'rate_remaining'       => (int) wp_remote_retrieve_header( $response, 'x-ratelimit-remaining' ),
            'rate_reset'           => (int) wp_remote_retrieve_header( $response, 'x-ratelimit-reset' ),
            'oauth_scopes'         => sanitize_text_field( (string) wp_remote_retrieve_header( $response, 'x-oauth-scopes' ) ),
            'accepted_permissions' => sanitize_text_field( (string) wp_remote_retrieve_header( $response, 'x-accepted-github-permissions' ) ),
            'request_id'           => sanitize_text_field( (string) wp_remote_retrieve_header( $response, 'x-github-request-id' ) ),
            'api_version'          => $this->api_version,
            'api_root'             => $this->api_root,
            'headers'              => is_object( $headers ) && method_exists( $headers, 'getAll' ) ? $headers->getAll() : array(),
        );

        if ( $status < 200 || $status >= 300 ) {
            $message = is_array( $decoded ) && ! empty( $decoded['message'] )
                ? sanitize_text_field( $decoded['message'] )
                : sprintf( __( 'GitHub returned HTTP %d.', 'githubupload' ), $status );

            if ( 401 === $status ) {
                $message = __( 'GitHub rejected the token. Confirm that it is active and copied completely.', 'githubupload' );
            } elseif ( 403 === $status && 0 === (int) $this->last_meta['rate_remaining'] ) {
                $message = __( 'The GitHub API rate limit has been reached. Try again after the reset time shown in diagnostics.', 'githubupload' );
            } elseif ( 404 === $status ) {
                $message = __( 'GitHub could not find this resource. Confirm the repository, branch, token access, and API URL.', 'githubupload' );
            } elseif ( 410 === $status ) {
                $message = __( 'The selected GitHub API version is no longer supported. Choose a supported API version in settings.', 'githubupload' );
            } elseif ( 422 === $status && is_array( $decoded ) && ! empty( $decoded['message'] ) ) {
                $message = sanitize_text_field( $decoded['message'] );
            }

            return new WP_Error(
                'githubupload_github_api_error',
                $message,
                array(
                    'status'   => $status,
                    'endpoint' => $endpoint,
                    'meta'     => $this->safe_meta(),
                    'response' => is_array( $decoded ) ? $decoded : array(),
                )
            );
        }

        return is_array( $decoded ) ? $decoded : array();
    }

    public function get_last_meta() {
        return $this->safe_meta();
    }

    public function get_authenticated_user() {
        return $this->request( 'GET', '/user' );
    }

    public function get_rate_limit() {
        return $this->request( 'GET', '/rate_limit' );
    }

    public function get_supported_versions() {
        return $this->request( 'GET', '/versions' );
    }

    public function list_repositories( $visibility = 'all', $max_pages = 3 ) {
        $all       = array();
        $max_pages = max( 1, min( 10, (int) $max_pages ) );
        $visibility = in_array( $visibility, array( 'all', 'public', 'private' ), true ) ? $visibility : 'all';

        for ( $page = 1; $page <= $max_pages; $page++ ) {
            $query = http_build_query(
                array(
                    'affiliation' => 'owner,collaborator,organization_member',
                    'visibility'  => $visibility,
                    'sort'        => 'updated',
                    'direction'   => 'desc',
                    'per_page'    => 100,
                    'page'        => $page,
                ),
                '',
                '&',
                PHP_QUERY_RFC3986
            );
            $items = $this->request( 'GET', '/user/repos?' . $query );
            if ( is_wp_error( $items ) ) {
                return $items;
            }
            $all = array_merge( $all, $items );
            if ( count( $items ) < 100 ) {
                break;
            }
        }

        return $all;
    }

    public function list_branches( $repository, $max_pages = 3 ) {
        $all       = array();
        $max_pages = max( 1, min( 10, (int) $max_pages ) );

        for ( $page = 1; $page <= $max_pages; $page++ ) {
            $items = $this->request(
                'GET',
                '/repos/' . $this->repo_path( $repository ) . '/branches?per_page=100&page=' . $page
            );
            if ( is_wp_error( $items ) ) {
                return $items;
            }
            $all = array_merge( $all, $items );
            if ( count( $items ) < 100 ) {
                break;
            }
        }

        return $all;
    }

    public function get_repository( $repository ) {
        return $this->request( 'GET', '/repos/' . $this->repo_path( $repository ) );
    }

    public function get_ref( $repository, $branch ) {
        return $this->request( 'GET', '/repos/' . $this->repo_path( $repository ) . '/git/ref/heads/' . $this->branch_path( $branch ) );
    }

    public function create_ref( $repository, $branch, $sha ) {
        return $this->request(
            'POST',
            '/repos/' . $this->repo_path( $repository ) . '/git/refs',
            array(
                'ref' => 'refs/heads/' . $branch,
                'sha' => $sha,
            )
        );
    }

    public function get_commit( $repository, $sha ) {
        return $this->request( 'GET', '/repos/' . $this->repo_path( $repository ) . '/git/commits/' . rawurlencode( $sha ) );
    }

    public function create_blob( $repository, $content ) {
        return $this->request(
            'POST',
            '/repos/' . $this->repo_path( $repository ) . '/git/blobs',
            array(
                'content'  => base64_encode( $content ), // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_encode
                'encoding' => 'base64',
            ),
            max( 120, $this->timeout )
        );
    }

    public function create_tree( $repository, $base_tree, array $entries ) {
        return $this->request(
            'POST',
            '/repos/' . $this->repo_path( $repository ) . '/git/trees',
            array(
                'base_tree' => $base_tree,
                'tree'      => $entries,
            ),
            max( 120, $this->timeout )
        );
    }

    public function create_commit( $repository, $message, $tree_sha, $parent_sha, array $author = array() ) {
        $body = array(
            'message' => $message,
            'tree'    => $tree_sha,
            'parents' => array( $parent_sha ),
        );

        if ( ! empty( $author['name'] ) && ! empty( $author['email'] ) && is_email( $author['email'] ) ) {
            $body['author'] = array(
                'name'  => sanitize_text_field( $author['name'] ),
                'email' => sanitize_email( $author['email'] ),
                'date'  => gmdate( 'c' ),
            );
            $body['committer'] = $body['author'];
        }

        return $this->request( 'POST', '/repos/' . $this->repo_path( $repository ) . '/git/commits', $body );
    }

    public function update_ref( $repository, $branch, $sha ) {
        return $this->request(
            'PATCH',
            '/repos/' . $this->repo_path( $repository ) . '/git/refs/heads/' . $this->branch_path( $branch ),
            array(
                'sha'   => $sha,
                'force' => false,
            )
        );
    }

    private function is_retryable_status( $status ) {
        return in_array( (int) $status, array( 429, 500, 502, 503, 504 ), true );
    }

    private function safe_meta() {
        $meta = $this->last_meta;
        unset( $meta['headers'] );
        return $meta;
    }

    private function repo_path( $repository ) {
        $parts = explode( '/', (string) $repository, 2 );
        return rawurlencode( $parts[0] ) . '/' . rawurlencode( isset( $parts[1] ) ? $parts[1] : '' );
    }

    private function branch_path( $branch ) {
        return implode( '/', array_map( 'rawurlencode', explode( '/', (string) $branch ) ) );
    }
}
