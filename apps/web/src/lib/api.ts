// Thin, typed client over the IRAQ SHIELD API. Every call hits the real
// backend — there is no mock layer.

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);
const PREFIX = "/api/v1";

export interface ApiError {
  code: string;
  message: string;
  request_id?: string;
}

export class ApiException extends Error {
  code: string;
  status: number;
  constructor(status: number, err: ApiError) {
    super(err.message);
    this.code = err.code;
    this.status = status;
  }
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  clearance_level: number;
  role_names: string[];
  permission_codes: string[];
  last_login_at: string | null;
  created_at: string;
}

export interface ServiceHealth {
  ok: boolean;
  latency_ms?: number;
  error?: string;
}

export interface Readiness {
  status: "ready" | "degraded";
  services: Record<string, ServiceHealth>;
}

async function parse<T>(resp: Response): Promise<T> {
  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    const err: ApiError = data?.error ?? {
      code: "error",
      message: `HTTP ${resp.status}`,
    };
    throw new ApiException(resp.status, err);
  }
  return data as T;
}

export async function login(email: string, password: string): Promise<TokenPair> {
  const resp = await fetch(`${BASE}${PREFIX}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return parse<TokenPair>(resp);
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export async function fetchMe(token: string): Promise<CurrentUser> {
  return parse<CurrentUser>(
    await fetch(`${BASE}${PREFIX}/auth/me`, { headers: authHeaders(token) }),
  );
}

// Readiness is unauthenticated (matches a real k8s readiness probe).
export async function fetchReadiness(): Promise<Readiness> {
  const resp = await fetch(`${BASE}/health/ready`);
  // 503 still returns a valid JSON body we want to render.
  const data = (await resp.json()) as Readiness;
  return data;
}

export interface AuditEntry {
  id: string;
  actor_email: string | null;
  action: string;
  outcome: string;
  ip_address: string | null;
  created_at: string;
}

export async function fetchAudit(token: string): Promise<AuditEntry[]> {
  return parse<AuditEntry[]>(
    await fetch(`${BASE}${PREFIX}/audit?limit=25`, { headers: authHeaders(token) }),
  );
}

// --- Collection (P1) ---------------------------------------------------- //
export interface Source {
  id: string;
  name: string;
  source_type: string;
  url: string;
  category: string | null;
  reliability: string;
  enabled: boolean;
  health: string;
  success_rate: number;
  total_runs: number;
  success_count: number;
  failure_count: number;
  consecutive_failures: number;
  avg_latency_ms: number;
  last_status: string | null;
  last_error: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  // P1.3 — editorial classification + Telegram public-channel fields
  source_class: string | null;
  verification_status: string | null;
  telegram_username: string | null;
  telegram_channel_id: number | null;
  telegram_title: string | null;
}

export interface VerifyResult {
  status: string;
  reason?: string;
  channel_id?: number;
  title?: string;
  username?: string;
  public_url?: string;
  posts_visible?: number;
}

export async function verifySource(token: string, id: string): Promise<VerifyResult> {
  return parse<VerifyResult>(
    await fetch(`${BASE}${PREFIX}/sources/${id}/verify`, {
      method: "POST",
      headers: authHeaders(token),
    }),
  );
}

export interface CollectionRun {
  id: string;
  source_id: string;
  status: string;
  http_status: number | null;
  items_seen: number;
  items_new: number;
  items_duplicate: number;
  items_versioned: number;
  items_discovered: number;
  items_failed: number;
  latency_ms: number | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export async function fetchSource(token: string, id: string): Promise<Source> {
  return parse<Source>(
    await fetch(`${BASE}${PREFIX}/sources/${id}`, { headers: authHeaders(token) }),
  );
}

export async function fetchSourceRuns(token: string, id: string): Promise<CollectionRun[]> {
  return parse<CollectionRun[]>(
    await fetch(`${BASE}${PREFIX}/sources/${id}/runs`, { headers: authHeaders(token) }),
  );
}

export interface ArchiveItem {
  id: string;
  source_id: string;
  url: string;
  canonical_url: string | null;
  external_id: string | null;
  title: string | null;
  published_at: string | null;
  collected_at: string;
  content_type: string | null;
  language: string | null;
  author: string | null;
  content_hash: string;
  fingerprint: string;
  version: number;
  is_current: boolean;
  size_bytes: number | null;
  raw_ref: string;
}

export async function fetchArchive(token: string, sourceId: string): Promise<ArchiveItem[]> {
  return parse<ArchiveItem[]>(
    await fetch(`${BASE}${PREFIX}/archive?source_id=${sourceId}&current_only=true`, {
      headers: authHeaders(token),
    }),
  );
}

export interface SearchArchiveFilters {
  source_id?: string;
  language?: string;
  author?: string;
  content_type?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export async function searchArchive(
  token: string,
  filters?: SearchArchiveFilters,
): Promise<ArchiveItem[]> {
  const params = new URLSearchParams();
  if (filters?.source_id) params.append("source_id", filters.source_id);
  if (filters?.language) params.append("language", filters.language);
  if (filters?.author) params.append("author", filters.author);
  if (filters?.content_type) params.append("content_type", filters.content_type);
  if (filters?.date_from) params.append("date_from", filters.date_from);
  if (filters?.date_to) params.append("date_to", filters.date_to);
  if (filters?.limit) params.append("limit", filters.limit.toString());

  const queryString = params.toString();
  const url = `${BASE}${PREFIX}/archive/search${queryString ? `?${queryString}` : ""}`;

  return parse<ArchiveItem[]>(
    await fetch(url, {
      headers: authHeaders(token),
    }),
  );
}

export async function searchArchiveFulltext(
  token: string,
  _query: string,
  limit: number = 100,
): Promise<ArchiveItem[]> {
  // Fulltext search stub — forwards to regular search endpoint
  // The backend may have a dedicated /archive/fulltext endpoint
  const params = new URLSearchParams();
  params.append("limit", limit.toString());
  const url = `${BASE}${PREFIX}/archive/search?${params.toString()}`;
  return parse<ArchiveItem[]>(
    await fetch(url, {
      headers: authHeaders(token),
    }),
  );
}

export interface SourcesDashboard {
  total: number;
  active: number;
  disabled: number;
  healthy: number;
  degraded: number;
  failed: number;
  pending: number;
  archive_items: number;
  recent_runs: CollectionRun[];
}

export async function fetchSources(token: string): Promise<Source[]> {
  return parse<Source[]>(
    await fetch(`${BASE}${PREFIX}/sources`, { headers: authHeaders(token) }),
  );
}

export async function fetchSourcesDashboard(token: string): Promise<SourcesDashboard> {
  return parse<SourcesDashboard>(
    await fetch(`${BASE}${PREFIX}/sources/dashboard`, { headers: authHeaders(token) }),
  );
}

// --- Events (P1.6) ---------------------------------------------------- //
export interface Event {
  id: string;
  title: string;
  description: string | null;
  occurred_at: string;
  status: string;
  severity: string;
  confidence: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  updated_by: string | null;
}

export interface EventArchive {
  event_id: string;
  archive_id: string;
  linked_at: string;
  linked_by: string | null;
}

export async function listEvents(
  token: string,
  limit?: number,
  offset?: number,
  status?: string,
  severity?: string,
): Promise<Event[]> {
  const params = new URLSearchParams();
  if (limit) params.append("limit", limit.toString());
  if (offset) params.append("offset", offset.toString());
  if (status) params.append("status_filter", status);
  if (severity) params.append("severity_filter", severity);

  const queryString = params.toString();
  const url = `${BASE}${PREFIX}/events${queryString ? `?${queryString}` : ""}`;

  return parse<Event[]>(
    await fetch(url, { headers: authHeaders(token) }),
  );
}

export async function getEvent(token: string, id: string): Promise<Event> {
  return parse<Event>(
    await fetch(`${BASE}${PREFIX}/events/${id}`, { headers: authHeaders(token) }),
  );
}

export async function createEvent(
  token: string,
  data: {
    title: string;
    description?: string;
    occurred_at: string;
    status?: string;
    severity?: string;
    confidence?: number;
  },
): Promise<Event> {
  return parse<Event>(
    await fetch(`${BASE}${PREFIX}/events`, {
      method: "POST",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  );
}

export async function updateEvent(
  token: string,
  id: string,
  data: Partial<{
    title: string;
    description: string | null;
    occurred_at: string;
    status: string;
    severity: string;
    confidence: number;
  }>,
): Promise<Event> {
  return parse<Event>(
    await fetch(`${BASE}${PREFIX}/events/${id}`, {
      method: "PATCH",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  );
}

export async function linkArchiveToEvent(
  token: string,
  eventId: string,
  archiveId: string,
): Promise<EventArchive> {
  return parse<EventArchive>(
    await fetch(`${BASE}${PREFIX}/events/${eventId}/archive/${archiveId}`, {
      method: "POST",
      headers: authHeaders(token),
    }),
  );
}

export async function unlinkArchiveFromEvent(token: string, eventId: string, archiveId: string): Promise<void> {
  const resp = await fetch(`${BASE}${PREFIX}/events/${eventId}/archive/${archiveId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!resp.ok) {
    const text = await resp.text();
    const data = text ? JSON.parse(text) : {};
    const err: ApiError = data?.error ?? {
      code: "error",
      message: `HTTP ${resp.status}`,
    };
    throw new ApiException(resp.status, err);
  }
}

// --- Entities (P1.7) ---------------------------------------------------- //
export interface Entity {
  id: string;
  entity_type: string;
  name: string;
  description: string | null;
  status: string;
  confidence: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  updated_by: string | null;
}

export interface ArchiveEntity {
  entity_id: string;
  archive_id: string;
  linked_at: string;
  linked_by: string | null;
}

export interface EventEntity {
  event_id: string;
  entity_id: string;
  linked_at: string;
  linked_by: string | null;
}

export interface EntityRelationship {
  id: string;
  from_entity_id: string;
  to_entity_id: string;
  relation_type: string;
  confidence: number;
  created_at: string;
  created_by: string | null;
}

export async function listEntities(
  token: string,
  limit?: number,
  offset?: number,
  entity_type?: string,
  status?: string,
): Promise<Entity[]> {
  const params = new URLSearchParams();
  if (limit) params.append("limit", limit.toString());
  if (offset) params.append("offset", offset.toString());
  if (entity_type) params.append("entity_type", entity_type);
  if (status) params.append("status", status);

  const queryString = params.toString();
  const url = `${BASE}${PREFIX}/entities${queryString ? `?${queryString}` : ""}`;

  return parse<Entity[]>(
    await fetch(url, { headers: authHeaders(token) }),
  );
}

export async function getEntity(token: string, id: string): Promise<Entity> {
  return parse<Entity>(
    await fetch(`${BASE}${PREFIX}/entities/${id}`, { headers: authHeaders(token) }),
  );
}

export async function createEntity(
  token: string,
  data: {
    entity_type: string;
    name: string;
    description?: string;
    status?: string;
    confidence?: number;
  },
): Promise<Entity> {
  return parse<Entity>(
    await fetch(`${BASE}${PREFIX}/entities`, {
      method: "POST",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  );
}

export async function updateEntity(
  token: string,
  id: string,
  data: Partial<{
    name: string;
    description: string | null;
    status: string;
    confidence: number;
  }>,
): Promise<Entity> {
  return parse<Entity>(
    await fetch(`${BASE}${PREFIX}/entities/${id}`, {
      method: "PATCH",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  );
}

export async function linkArchiveToEntity(
  token: string,
  entityId: string,
  archiveId: string,
): Promise<ArchiveEntity> {
  return parse<ArchiveEntity>(
    await fetch(`${BASE}${PREFIX}/entities/${entityId}/archive/${archiveId}`, {
      method: "POST",
      headers: authHeaders(token),
    }),
  );
}

export async function unlinkArchiveFromEntity(
  token: string,
  entityId: string,
  archiveId: string,
): Promise<void> {
  const resp = await fetch(`${BASE}${PREFIX}/entities/${entityId}/archive/${archiveId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!resp.ok) {
    const text = await resp.text();
    const data = text ? JSON.parse(text) : {};
    const err: ApiError = data?.error ?? {
      code: "error",
      message: `HTTP ${resp.status}`,
    };
    throw new ApiException(resp.status, err);
  }
}

export async function linkEntityToEvent(
  token: string,
  entityId: string,
  eventId: string,
): Promise<EventEntity> {
  return parse<EventEntity>(
    await fetch(`${BASE}${PREFIX}/entities/${entityId}/event/${eventId}`, {
      method: "POST",
      headers: authHeaders(token),
    }),
  );
}

export async function unlinkEntityFromEvent(
  token: string,
  entityId: string,
  eventId: string,
): Promise<void> {
  const resp = await fetch(`${BASE}${PREFIX}/entities/${entityId}/event/${eventId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!resp.ok) {
    const text = await resp.text();
    const data = text ? JSON.parse(text) : {};
    const err: ApiError = data?.error ?? {
      code: "error",
      message: `HTTP ${resp.status}`,
    };
    throw new ApiException(resp.status, err);
  }
}

export async function createRelationship(
  token: string,
  fromId: string,
  toId: string,
  data: {
    relation_type: string;
    confidence?: number;
  },
): Promise<EntityRelationship> {
  return parse<EntityRelationship>(
    await fetch(`${BASE}${PREFIX}/entities/${fromId}/relate/${toId}`, {
      method: "POST",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  );
}

export async function deleteRelationship(token: string, relationshipId: string): Promise<void> {
  const resp = await fetch(`${BASE}${PREFIX}/relationships/${relationshipId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!resp.ok) {
    const text = await resp.text();
    const data = text ? JSON.parse(text) : {};
    const err: ApiError = data?.error ?? {
      code: "error",
      message: `HTTP ${resp.status}`,
    };
    throw new ApiException(resp.status, err);
  }
}

export interface EntityRelationshipsResponse {
  outgoing: EntityRelationship[];
  incoming: EntityRelationship[];
}

export async function getEntityRelationships(
  token: string,
  entityId: string,
): Promise<EntityRelationshipsResponse> {
  return parse<EntityRelationshipsResponse>(
    await fetch(`${BASE}${PREFIX}/entities/${entityId}/relationships`, {
      headers: authHeaders(token),
    }),
  );
}
