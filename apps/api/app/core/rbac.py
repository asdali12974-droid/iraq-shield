"""Canonical RBAC catalog.

These are *authorization scopes* and role definitions — access-control
configuration, not feature implementations. A scope listed here does not imply
the corresponding feature exists yet; endpoints for later phases (sources,
reports, threat, analyst...) are not part of P0. The scopes are defined now so
roles are stable and future endpoints can enforce them without a schema change.

Only the scopes marked ACTIVE below are enforced by an endpoint in P0.
"""
from __future__ import annotations

# --- Permission catalog: code -> human description --- #
PERMISSIONS: dict[str, str] = {
    # ACTIVE in P0
    "iam:me:read": "Read own profile",
    "system:health:read": "Read detailed service health",
    "audit:read": "Read the audit log",
    "admin:users:read": "List and view users",
    "admin:users:manage": "Create, update, deactivate users and assign roles",
    "admin:roles:read": "List roles and permissions",
    # ACTIVE in P1 (collection)
    "sources:read": "View collection sources and health",
    "sources:manage": "Create, update, enable/disable collection sources",
    "collection:run": "Trigger a collection job for a source",
    "archive:read": "Read the raw historical archive",
    # RESERVED for later phases (defined, not yet enforced by any endpoint)
    "documents:read": "Read ingested documents",
    "events:read": "Read extracted events",
    "reports:read": "Read intelligence reports",
    "reports:write": "Draft intelligence reports",
    "reports:approve": "Approve and publish reports",
    "search:query": "Use the intelligence search engine",
    "graph:read": "Explore the knowledge graph",
    "threat:read": "View threat assessments and alerts",
    "analyst:query": "Query the AI analyst",
}

# Scopes actually enforced by a live endpoint (P0 + P1 collection).
ACTIVE_IN_P0: frozenset[str] = frozenset(
    {
        "iam:me:read",
        "system:health:read",
        "audit:read",
        "admin:users:read",
        "admin:users:manage",
        "admin:roles:read",
        "sources:read",
        "sources:manage",
        "collection:run",
        "archive:read",
    }
)

# --- Roles: name -> (description, permission codes) --- #
_VIEWER = {
    "iam:me:read",
    "sources:read",
    "archive:read",
    "documents:read",
    "events:read",
    "reports:read",
    "search:query",
    "graph:read",
    "threat:read",
}
_ANALYST = _VIEWER | {"reports:write", "analyst:query"}
_SENIOR = _ANALYST | {"reports:approve", "collection:run", "system:health:read"}
_COLLECTOR = _VIEWER | {
    "sources:manage",
    "collection:run",
    "system:health:read",
}

ROLES: dict[str, tuple[str, set[str]]] = {
    "viewer": ("Read-only access to published intelligence", _VIEWER),
    "analyst": ("Search, explore, and draft reports", _ANALYST),
    "senior_analyst": ("Approve reports, confirm alerts, tune rules", _SENIOR),
    "collector_manager": ("Manage sources and collectors", _COLLECTOR),
    "admin": ("Full administrative access", set(PERMISSIONS.keys())),
}
