# IRAQ SHIELD — Security Posture (P0)

Result of the P0 hardening & audit pass. Status legend: **PASS** (implemented &
tested), **WARNING** (acceptable for local/dev; must change for production —
documented), **N/A** (not present in P0).

## Authentication
- **PASS** Argon2id password hashing (unique salt per hash).
- **PASS** JWT access (30m) + refresh (7d); `decode` requires `sub/type/iat/exp/jti`.
- **PASS** Refresh tokens persisted by `jti`; **rotation** on every refresh;
  **reuse detection** burns the whole token family; `/auth/logout` revokes.
- **PASS** Brute-force throttling (Redis): per-email and per-IP failure windows,
  `429 + Retry-After` on lockout. Fails open on Redis outage (logged) so the
  platform can't be self-DoS'd; every attempt is still audited.
- **PASS** Password policy (≥12 chars, ≥3 classes, no triple repeats, denylist),
  enforced on user creation and on the bootstrap admin (hard-fail in production).

## RBAC
- **PASS** Every non-public endpoint requires a specific permission; unauthenticated
  access returns 401, insufficient permission 403 (tested for all four admin/audit routes).
- **PASS** Privilege escalation blocked: a viewer cannot reach admin routes or create users.
- **PASS** Permission denials are written to the audit log (`authz.permission_denied`).

## Audit log
- **PASS** Append-only enforced by a database trigger (UPDATE/DELETE raise); no API
  can mutate or delete entries.
- **PASS** Records login success/failure/blocked, logout, refresh success/failure,
  permission-denied, and admin actions (user creation).
- **PASS** No passwords, secrets, or tokens are ever written (verified by test + live grep).

## Secrets & configuration
- **PASS** No real secrets in code or Git; `.env` is gitignored; `.env.example` holds placeholders.
- **PASS** Production-safety guard aborts startup on default/weak `JWT_SECRET`
  (<32 chars), default DB/MinIO/Neo4j passwords, `CORS=*`, or `DEBUG=true`.
- **PASS** Validation errors (422) no longer echo submitted input (no password leakage).

## API security
- **PASS** Security headers on every response: `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy`,
  `Permissions-Policy`, `Cache-Control: no-store`, COOP/CORP.
- **PASS** CORS is an explicit allowlist (never `*`), credentialed.
- **PASS** Request validation via Pydantic; 500s never leak internals.
- **PASS** Rate limiting on the login path. General per-route rate limiting is
  expected at the reverse proxy in production (**WARNING**).
- **N/A** No file uploads in P0.

## Docker
- **PASS** API container runs as a non-root user (uid 10001).
- **PASS** All published ports bind to `127.0.0.1` only (datastores not exposed on external interfaces).
- **PASS** Redis requires a password; Postgres/Neo4j/MinIO use credentials from `.env`.
- **PASS** Healthchecks, `restart: unless-stopped`, named volumes, single bridge network.
- **WARNING (prod)** OpenSearch security plugin is disabled for local dev — production
  must enable auth + TLS.
- **WARNING (prod)** nginx master runs as root to bind :80 (standard); front with a
  reverse proxy / use an unprivileged image in production.

## Database
- **PASS** Indexes on `users.email`, audit action/created/actor, refresh-token user/active.
- **PASS** Foreign keys with `ON DELETE CASCADE` on associations and refresh tokens.
  Audit log intentionally has no FK to users (must survive user deletion).
- **PASS** CHECK constraints: `users.clearance_level ∈ [0,5]`, `audit_log.outcome ∈ {success,failure}`.
- **PASS** Reversible Alembic migrations; connection pooling with `pool_pre_ping`.
- **WARNING (prod)** The app connects as the DB superuser in local setup; production
  should use a least-privilege role (the append-only trigger already blocks audit
  mutation for all roles).

## Frontend
- **PASS** No secrets in the frontend (only the API base URL).
- **PASS** Routes are guarded; unauthenticated users are redirected to login.
- **PASS** CSP + security headers served by nginx.
- **WARNING** Access token stored in `localStorage` (XSS-exfiltration risk). Mitigated
  by short TTL, refresh rotation, and CSP; an httpOnly-cookie flow is a future option.

## Dependencies
- **PASS** Backend: `pip-audit` clean for runtime deps after upgrading
  `pyjwt→2.13.0`, `fastapi→0.141.1`/`starlette→1.6.0`, `python-multipart→0.0.32`.
- **PASS** Frontend: `npm audit` reports 0 vulnerabilities after
  `react-router-dom→7`, `vite→7`, `postcss→8.5.26`.
- **WARNING** Dev-only test tooling (`pytest`, `setuptools`) carry advisories fixed in
  newer majors; not shipped in the production image. Track in CI.

## Data sovereignty
- **PASS** No external calls: the Google Fonts CDN was removed from the frontend
  (system fonts). A test guards against reintroducing any external host.
- **PASS** No telemetry/analytics. All clients (Postgres/Redis/MinIO/OpenSearch/Neo4j/LLM)
  target internal services only.
- **WARNING (ops)** Container images are pulled from public registries; mirror them
  internally for a fully air-gapped deployment.

## Verification
- 47 automated tests pass, 1 skipped (the full-stack readiness test, which needs
  the whole compose stack up); `ruff` clean; every item above additionally
  exercised live via HTTP.
