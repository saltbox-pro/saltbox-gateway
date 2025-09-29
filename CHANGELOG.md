# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add computed fields `total_minions` and `minions_count_by_status` to task schema for WebSocket task updates.
- Add `RequestIDMiddleware` and `Server-Timing` headers to surface request IDs and request duration for diagnostics.
- Add permissions router and integrate permission checks in `ProxyService` to validate access for service paths.
- Add FastAPI metrics export endpoint to expose runtime metrics.
- Add POST `/query-translator` endpoint and improve `AsyncOpaClient` to support query translation.
- Add a WebSocket endpoint for broadcasting task updates.
- Add `AsyncOpaClient`, `MongoQueryVisitor`, `SQLQueryVisitor` and Rego AST classes to support OPA policy checks and query generation.
- Add service discovery and health-checking features: `DiscoveryService`, `discovery_router` (register/unregister/list), `HealthChecker`, balancing strategies and `ServiceDAO`.
- Add `KeycloakOIDC` authentication utilities and `AuthMiddleware` with Redis caching for OIDC tokens.
- Add secure WebSocket handling with token management and related error classes.
- Add `get_custom_openapi_schema` to generate a customized OpenAPI schema for the FastAPI app.

### Changed

- Replace ad-hoc HTTPX helper with a configurable `HttpxClientSingletoneFactory`; add granular HTTP client timeouts and an idempotent retry policy.
- Refactor `ProxyService` request handling: initialize and parse `raw_body`/`body` safely, normalize headers, strip `content-type`/`content-length` for non-body methods, and rename `proxy_request` → `api_proxy` and `proxy_static` → `proxy_static_file`.
- Improve query and cache handling: preserve multi-value query parameters, include serialized query params and user ID in cache keys, safely decode base64 cached responses, and filter hop-by-hop headers from cached responses.
- Simplify access-control and OPA integration: set default OPA action when missing, improve permission-check flow, and refactor permissions paths handling.
- Update configuration and settings: add `swagger_ui_oauth2_redirect_url`, `static_proxy_prefix`, include `scheduler` and `inventory` in `official_modules`, and set default `server_outer_socket` to `localhost` with additional HTTPX timeout settings.
- Refactor error handling to use shared exception classes (migrate to `SaltBoxBaseError`/new API error classes) and extend `ApiProxyRequestError` to carry `status_code` and clearer detail extraction.
- Refactor service instance handling: replace instance-add with merge semantics and improve healthy-instance selection and instance merging logic.

### Fixed

- Fix job WebSocket schema to match expected fields for task updates.
- Fix static proxy error handling to return correct error responses when static upstreams fail.
- Fix API proxy error handling and error detail extraction (log JSON parse errors and include status code when available).
- Fix user ID retrieval and related proxy request handling edge cases.
- Address type checking and mypy issues discovered during refactors.

### Removed

- Remove deprecated `proxy_old.py` and replace it with the refactored proxy implementation.
- Remove schemas that have been moved to the `saltbox-sdk` repository.
- Remove unused startup scripts and tooling (`uvicorn.sh`, `shell_init.sh`) and `setuptools_scm` from `pyproject.toml`.
- Remove obsolete helpers such as `custom_http_handler` that are no longer required after error-handling refactors.
