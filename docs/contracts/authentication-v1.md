# Authentication v1

`authentication-v1` defines the replaceable authentication boundary. All modes resolve
to the same `(user_id, organization_id)` identity tuple, validated against database
membership, so downstream RBAC is mode-agnostic. No request header, query, or client
payload is ever accepted as an identity source.

## Modes

| Mode | Use | Token | Key |
| --- | --- | --- | --- |
| `disabled` | local development only (`DEV_ACTOR_ID`) | none | — |
| `jwt_hs256` | platform-issued tokens | HS256 JWT | symmetric secret (≥32 chars) |
| `oidc` | enterprise IdP (Entra ID, Keycloak, Auth0) | RS256 JWT | asymmetric, via JWKS |

## OIDC / RS256

When `AUTH_MODE=oidc`, the API verifies RS256 tokens against the identity provider's
JWKS document:

* `AUTH_OIDC_JWKS_URL` — the JWKS endpoint. **Must be https.**
* `AUTH_OIDC_ISSUER` / `AUTH_OIDC_AUDIENCE` — the expected `iss` / `aud`.
* `AUTH_OIDC_JWKS_CACHE_SECONDS` — bounded key cache TTL (default 300).

Key rotation is supported without a restart: an unknown `kid` triggers a single JWKS
refresh and retry. Keys are cached by `kid` for the verifier's lifetime.

### Red lines

* **Algorithm allowlist.** Only `RS256` is accepted in OIDC mode. `HS256`, `none`, and
  any other algorithm are rejected, so a token can never downgrade to a symmetric or
  unsigned form.
* **Fail closed.** Any signature, key, JWKS, or claim problem yields `invalid_token`;
  verification never returns an identity it could not cryptographically confirm.
* **Bounded input.** Oversized tokens are rejected before parsing; JWKS fetching has a
  short timeout and a bounded cache.
* **HTTPS only.** The JWKS URL scheme is validated at startup; non-https is rejected.

## Auditing

Authentication outcomes that can be attributed to an existing organization are
recorded best-effort as `auth.failed` audit events on the organization boundary:

* **Scope.** Only failures with a resolvable organization (e.g. a validly-signed token
  for an org the user does not belong to → `permission_denied`) are persisted; a token
  referencing a non-existent tenant never writes a record.
* **Sentinel actor.** The rejected principal may be unknown, so the event uses a fixed
  non-user sentinel actor id and records the stable `failure_code` in metadata.
* **Never blocking.** Persistence runs in an independent session; an audit failure is
  logged and swallowed rather than surfacing as a 5xx or suppressing the 401/403.

## Known limits

Login/refresh sessions, refresh tokens, and server-side revocation are not yet
implemented; Bearer tokens are stateless. These are tracked as follow-up hardening.
