# ADR 0001 — Native JWT authentication for P0 (Keycloak deferred)

- Status: Accepted
- Date: 2026-08-29
- Phase: P0

## Context
The architecture names **Keycloak (OIDC)** as the identity provider. P0 must
deliver a *testable, production-oriented* authentication and RBAC foundation.
Requiring a running Keycloak instance to exercise login/RBAC/audit would:
- make the auth foundation untestable without an external service, and
- pull an external moving part into the very first, most-scrutinized layer.

The user's constraints also stress: no external services used to paper over
missing implementation, and everything real and tested.

## Decision
Implement authentication and RBAC **natively in the API** for P0:
- Argon2id password hashing (`core/security.py`).
- JWT access + refresh tokens, type-tagged.
- Roles/permissions in Postgres, enforced by a `require_permission` dependency.
- Append-only audit log at the database level.

Keycloak/OIDC integration is deferred to the hardening phase (P10). All auth
logic is isolated behind `core/security.py` and `modules/iam/deps.py`, so
swapping token verification to validate Keycloak-issued OIDC tokens (JWKS)
touches only those seams — routes and RBAC checks stay unchanged.

## Consequences
- **Positive:** P0 auth is fully runnable and unit/integration-tested with no
  external IdP. No fake or stubbed auth. Clear upgrade seam.
- **Positive:** Internal/on-prem email domains (e.g. `*.local`, `*.internal`)
  are accepted — strict public-email validation was intentionally dropped, since
  a sovereign on-prem deployment commonly uses non-public domains.
- **Negative / follow-up:** Features Keycloak provides out of the box (SSO,
  social/LDAP federation, admin console, token revocation lists) are not present
  in P0. These are scoped into P10, where the native layer is either fronted by
  or replaced with Keycloak. Until then, refresh-token revocation is limited to
  short TTLs.
