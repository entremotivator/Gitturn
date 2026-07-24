<?php

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
    exit;
}

$settings = get_option( 'githubupload_settings', array() );
if ( ! empty( $settings['delete_on_uninstall'] ) ) {
    delete_option( 'githubupload_settings' );
    delete_option( 'githubupload_history' );
}
