# Keychain Auth Specification

## Purpose

Securely extract, parse, and cache Google Cloud Code Assist OAuth credentials from macOS Keychain to authenticate upstream requests without external dependencies.

## Requirements

### Requirement: Keychain Credential Extraction

The auth module SHALL execute the macOS `security` CLI to retrieve stored credentials for service `gemini` and account `antigravity`. The module SHALL strip the `go-keyring-base64:` prefix, decode base64 data, and parse JSON containing `token.access_token` and `token.expiry`. If the entry is missing or decoding fails, the module MUST raise an `AuthenticationError`.

#### Scenario: Valid Keychain extraction
- GIVEN a macOS Keychain entry for service `gemini` and account `antigravity`
- WHEN `KeychainTokenProvider.get_token()` is called with an empty cache
- THEN the system executes `security find-generic-password -s gemini -a antigravity -w`
- AND returns the extracted access token and expiration timestamp.

#### Scenario: Missing Keychain entry
- GIVEN no Keychain entry exists for `gemini/antigravity`
- WHEN `KeychainTokenProvider.get_token()` executes
- THEN the system catches the non-zero CLI exit code
- AND raises `AuthenticationError` with diagnostic instructions to log into Antigravity.

### Requirement: TTL In-Memory Token Caching

The auth module MUST maintain a thread-safe in-memory cache for the active access token. The cache MUST consider a token valid only when `current_time < expiry - 60` seconds. Valid cached tokens MUST be returned immediately without calling the Keychain CLI. When expired or within the 60-second margin, the module SHALL refresh credentials from Keychain.

#### Scenario: Cached token reuse
- GIVEN a cached access token with expiry 15 minutes in the future
- WHEN `get_token()` is invoked concurrently by multiple threads
- THEN the system returns the cached token without executing subprocess calls.

#### Scenario: Expired token refresh
- GIVEN a cached token whose expiry is within 60 seconds of current time
- WHEN `get_token()` is invoked
- THEN the system detects expiration, reads the latest token from Keychain, and updates the cache.

### Requirement: Cache Invalidation and 401 Re-Read

The auth module MUST expose an `invalidate()` method. Upon receiving an upstream HTTP 401 Unauthorized response, the client SHALL invalidate the cache and attempt exactly one immediate Keychain re-read to obtain a freshly refreshed token before failing.

#### Scenario: Force refresh on upstream 401
- GIVEN an invalidated token cache following an upstream 401 response
- WHEN `get_token(force_refresh=True)` is called
- THEN the system bypasses cache, reads Keychain anew, and caches the new token.
