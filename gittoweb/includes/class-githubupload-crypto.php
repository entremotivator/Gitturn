<?php

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

/**
 * Small encryption helper for the stored token.
 *
 * A wp-config.php constant is still preferable for production:
 * define( 'GITHUBUPLOAD_TOKEN', 'github_pat_...' );
 */
final class GitHubUpload_Crypto {
    const PREFIX_ENCRYPTED = 'ghu2e:';
    const PREFIX_FALLBACK  = 'ghu2p:';
    const PREFIX_LEGACY    = 'ghuv1:';

    public static function encrypt( $value ) {
        $value = trim( (string) $value );

        if ( '' === $value ) {
            return '';
        }

        if ( ! function_exists( 'openssl_encrypt' ) ) {
            return self::PREFIX_FALLBACK . base64_encode( $value ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_encode
        }

        try {
            $iv = random_bytes( 12 );
        } catch ( Exception $exception ) {
            return self::PREFIX_FALLBACK . base64_encode( $value ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_encode
        }

        $tag    = '';
        $cipher = openssl_encrypt( $value, 'aes-256-gcm', self::key(), OPENSSL_RAW_DATA, $iv, $tag );

        if ( false === $cipher || '' === $tag ) {
            return self::PREFIX_FALLBACK . base64_encode( $value ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_encode
        }

        return self::PREFIX_ENCRYPTED . base64_encode( $iv . $tag . $cipher ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_encode
    }

    public static function decrypt( $value ) {
        $value = (string) $value;

        if ( '' === $value ) {
            return '';
        }

        if ( 0 === strpos( $value, self::PREFIX_FALLBACK ) ) {
            $plain = base64_decode( substr( $value, strlen( self::PREFIX_FALLBACK ) ), true ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_decode
            return false === $plain ? '' : $plain;
        }

        if ( 0 === strpos( $value, self::PREFIX_ENCRYPTED ) ) {
            if ( ! function_exists( 'openssl_decrypt' ) ) {
                return '';
            }

            $payload = base64_decode( substr( $value, strlen( self::PREFIX_ENCRYPTED ) ), true ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_decode
            if ( false === $payload || strlen( $payload ) < 29 ) {
                return '';
            }

            $iv     = substr( $payload, 0, 12 );
            $tag    = substr( $payload, 12, 16 );
            $cipher = substr( $payload, 28 );
            $plain  = openssl_decrypt( $cipher, 'aes-256-gcm', self::key(), OPENSSL_RAW_DATA, $iv, $tag );

            return false === $plain ? '' : $plain;
        }

        if ( 0 === strpos( $value, self::PREFIX_LEGACY ) ) {
            return self::decrypt_legacy( $value );
        }

        // Migration support for installations that stored a plain token in v1.
        return $value;
    }

    public static function fingerprint( $value ) {
        $value = trim( (string) $value );
        if ( '' === $value ) {
            return '';
        }

        return substr( hash( 'sha256', $value ), 0, 10 ) . '…' . substr( $value, -4 );
    }

    private static function decrypt_legacy( $value ) {
        $payload = base64_decode( substr( $value, strlen( self::PREFIX_LEGACY ) ), true ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_decode
        if ( false === $payload ) {
            return '';
        }

        if ( function_exists( 'openssl_decrypt' ) && strlen( $payload ) >= 17 ) {
            $iv     = substr( $payload, 0, 16 );
            $cipher = substr( $payload, 16 );
            $plain  = openssl_decrypt( $cipher, 'AES-256-CBC', self::key(), OPENSSL_RAW_DATA, $iv );
            if ( false !== $plain ) {
                return $plain;
            }
        }

        return $payload;
    }

    private static function key() {
        $material  = defined( 'AUTH_KEY' ) ? AUTH_KEY : wp_salt( 'auth' );
        $material .= defined( 'SECURE_AUTH_KEY' ) ? SECURE_AUTH_KEY : wp_salt( 'secure_auth' );
        $material .= defined( 'LOGGED_IN_KEY' ) ? LOGGED_IN_KEY : wp_salt( 'logged_in' );

        return hash( 'sha256', $material, true );
    }
}
