<?php
/**
 * Plugin Name: GitHubUpload
 * Plugin URI:  https://github.com/entremotivator/githubupload
 * Description: Securely upload WordPress-selected folders or ZIP archives to GitHub.com or GitHub Enterprise with repository discovery, branch controls, diagnostics, and atomic commits.
 * Version:     2.0.0
 * Author:      D Hudson
 * License:     GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: githubupload
 * Requires at least: 6.2
 * Requires PHP: 7.4
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'GITHUBUPLOAD_VERSION', '2.0.0' );
define( 'GITHUBUPLOAD_FILE', __FILE__ );
define( 'GITHUBUPLOAD_DIR', plugin_dir_path( __FILE__ ) );
define( 'GITHUBUPLOAD_URL', plugin_dir_url( __FILE__ ) );

require_once GITHUBUPLOAD_DIR . 'includes/class-githubupload-crypto.php';
require_once GITHUBUPLOAD_DIR . 'includes/class-githubupload-api.php';
require_once GITHUBUPLOAD_DIR . 'includes/class-githubupload.php';

register_activation_hook( __FILE__, array( 'GitHubUpload', 'activate' ) );

GitHubUpload::instance();
