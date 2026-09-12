# IRAQ SHIELD — Architecture (P0)

This document describes the components delivered in **P0 (Foundations)** and how
they relate. The full platform vision (collection, GEOINT, threat engine, AI
analyst, etc.) is captured separately; here we describe only what exists in code
today and the seams left for later phases.

## Guiding constraints (enforced, not aspirational)
- **Public sources only**, on-prem, no external API as a core dependency.
- **No mock data.** The system runs on real data. P0 ships zero domain sample
  data; only RBAC *configuration* (roles/permissions) and one real admin account
  created from environment variables are seeded.
- **No feature façades.** The UI shows P1–P9 as explicitly "not implemented".
  Nothing pretends to work.
- **Provenance-first** data model (prepared in the schema seams, exercised from P1).

---

## Component map

```
                       ┌─────────────────────────────┐
   Browser  ──────────▶│  web (React + TS, nginx)     │
                       │  login + operations dashboard│
                       └──────────────┬──────────────┘
                                      │ HTTPS/JSON (CORS allowlist)
                                      ▼
                       ┌─────────────────────────────┐
                       │  api (FastAPI, modular)      │
                       │  ┌───────────────────────┐  │
                       │  │ modules/iam   (auth,RBAC)│ │
                       │  │ modules/audit (append-only)│
                       │  │ modules/health(probes)  │  │
                       │  └───────────────────────┘  │
                       │  core: config·logging·      │
                       │        security·errors·mw   │
                       └───┬───────┬───────┬───────┬──┘
                           │       │       │       │
         ┌─────────────────┘       │       │       └───────────────┐
         ▼                 ▼       ▼       ▼                        ▼
   ┌───────────┐   ┌──────────┐ ┌──────┐ ┌──────────┐        ┌──────────┐
   │ postgres  │   │  redis   │ │minio │ │opensearch│        │  neo4j   │
   │ (source of│   │ (queue/  │ │(raw  │ │ (search  │        │ (knowledge│
   │  truth)   │   │  cache)  │ │archive)│ index)   │        │  graph)  │
   └───────────┘   └──────────┘ └──────┘ └──────────┘        └──────────┘
     P0: IAM+audit   P0: health   P0:health  P0: health         P0: health
     P1+: domain     P1+: tasks   P1+: store P6: index          P5: graph
```

In P0 the API **actively uses** PostgreSQL (all reads/writes) and probes the
other four datastores for readiness. Redis, MinIO, OpenSearch, and Neo4j are
provisioned and health-checked now so later phases plug in without infra churn.

---

## Backend structure (`apps/api/app`)

| Path | Responsibility |
|---|---|
| `core/config.py` | Typed settings from `IS_*` env vars; refuses unsafe production defaults. |
| `core/logging.py` | Structured (JSON) logging with per-request correlation IDs. |
| `core/security.py` | Argon2id password hashing; JWT issue/verify (access + refresh). |
| `core/errors.py` | Uniform error envelope; internal details logged, never leaked. |
| `core/middleware.py` | Request-id + access logging middleware. |
| `core/rbac.py` | Canonical permission catalog and role→permission mapping. |
| `db/base.py`, `db/session.py` | Declarative base, async engine/session. |
| `models/iam.py` | `User`, `Role`, `Permission`, associations. |
| `models/audit.py` | `AuditLog` (append-only). |
| `modules/iam/` | Service, dependencies (`get_current_user`, `require_permission`), routes. |
| `modules/audit/` | Write service + read-only endpoint. |
| `modules/health/` | Real dependency probes + `/health`, `/health/ready`. |
| `alembic/` | Migrations (schema only; extensions provisioned by the DB image). |

Module boundaries are drawn so any module can later be extracted into its own
service without rewrites (the "modular monolith" seam).

---

## Data model (P0 tables)

```
users ──< user_roles >── roles ──< role_permissions >── permissions
  │
  └── (audit_log references actors by id/email, but is deliberately
       NOT a foreign key — audit rows must survive user deletion)

audit_log   append-only: a BEFORE UPDATE/DELETE trigger raises, so tampering
            is blocked at the database level, not just in application code.
```

Extensions **postgis**, **vector**, **timescaledb** are enabled by
`infra/postgres/init/00-extensions.sql` (run by the DB image on first init),
not by application migrations. P0 tables don't use them; P3/P4/P6/P9 will.

---

## Security model

- **AuthN:** email + password → Argon2id verify → JWT access (30 min) + refresh
  (7 days). Refresh tokens are type-tagged and cannot be used as access tokens.
- **AuthZ (RBAC):** each protected route declares a required permission via
  `require_permission("...")`. A user's effective permissions are the union of
  its roles' permissions. Clearance level is stored for later data-classification
  gating.
- **Audit:** sensitive actions (login success/failure, user creation, ...) are
  written to `audit_log` with actor, action, outcome, IP, and timestamp. The log
  is append-only and readable only with `audit:read`.
- **Config safety:** production startup aborts if the JWT secret or DB password
  are left at their insecure defaults.

Native auth is a P0 decision recorded in `docs/adr/0001-native-auth-for-p0.md`;
Keycloak/OIDC integration is planned for the hardening phase and the call sites
(`core/security.py`, `modules/iam/deps.py`) are the only places that change.

---

## Frontend structure (`apps/web/src`)

| Path | Responsibility |
|---|---|
| `lib/api.ts` | Typed client over the real API. No mock layer. |
| `lib/auth.tsx` | Auth context; token persistence; `/auth/me` resolution. |
| `pages/Login.tsx` | Real login form. |
| `pages/Dashboard.tsx` | Current user, service health, capability map, audit feed. |
| `components/ServiceHealth.tsx` | Renders real `/health/ready` results (green/red). |
| `components/PhasePanel.tsx` | Honest capability map: P0 active, P1–P9 not built. |

---

## What P0 deliberately excludes
Collection (web/Telegram), enrichment, GEOINT, timeline, knowledge-graph
building, search, threat engine, AI analyst. These are separate phases; their
datastores are present and healthy but no code writes domain data yet.
