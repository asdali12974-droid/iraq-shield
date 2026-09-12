# ADR 0002 — P0 hardening decisions

- Status: Accepted
- Date: 2026-08-29
- Phase: P0 (hardening pass)

## Context
Before P1, P0 underwent a security audit. Several decisions needed recording.

## Decisions

1. **Refresh tokens are persisted and revocable.** Stateless JWTs cannot be
   revoked. We store each refresh token's `jti` and honor a token only if its row
   is present, unexpired, and unrevoked. Refresh **rotates** (old revoked, new
   issued); presenting a revoked token is treated as **reuse/theft** and revokes
   the user's whole token family. `/auth/logout` revokes the presented token.

2. **Login throttling fails OPEN on Redis outage.** Brute-force counters live in
   Redis. If Redis is unavailable the login path proceeds (logging a warning)
   rather than locking everyone out. Rationale: a sovereign on-prem system must
   not be self-DoS'able by a cache blip, and every attempt is still audited. The
   residual risk (a brute-force window during a Redis outage) is accepted and
   documented.

3. **Validation errors do not echo submitted input.** Pydantic's default error
   body includes the offending value, which can be a password. We strip `input`
   and `ctx`, keeping only `type/loc/msg`.

4. **Published ports bind to 127.0.0.1.** Datastores are never exposed on external
   interfaces from compose; production terminates TLS at a reverse proxy in front
   of `api`/`web` and keeps datastores off the host entirely.

5. **Data sovereignty is test-enforced.** The frontend must make no third-party
   requests; the Google Fonts CDN was removed and a test fails the build if any
   external host reappears.

6. **Dependency CVEs are pinned to patched releases.** `pip-audit` and `npm audit`
   run clean for runtime deps (pyjwt, starlette/fastapi, python-multipart on the
   backend; react-router, vite, postcss on the frontend). Dev-only tooling
   advisories are tracked in CI, not shipped.

## Consequences
- Sessions are now revocable and observable, at the cost of a DB round-trip per
  refresh and a `refresh_tokens` table (migration 0002).
- A few production-only items remain **WARNING** (OpenSearch security plugin,
  least-privilege DB role, nginx-as-root, token-in-localStorage) — see
  `docs/SECURITY.md`. None are P0 blockers; each has a documented remediation.
