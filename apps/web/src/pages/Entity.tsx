import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  getEntity,
  updateEntity,
  createEntity,
  linkArchiveToEntity,
  unlinkArchiveFromEntity,
  linkEntityToEvent,
  unlinkEntityFromEvent,
  createRelationship,
  deleteRelationship,
  getEntityRelationships,
  searchArchive,
  listEvents,
  listEntities,
  type Entity,
  type EntityRelationship,
  type ArchiveItem,
  type Event,
  type ApiException,
} from "../lib/api";
import { Card, Eyebrow, Badge } from "../components/ui";

const ENTITY_TYPE_OPTIONS = ["PERSON", "ORGANIZATION", "LOCATION", "VEHICLE", "FACILITY", "WEAPON", "EVENT"];
const STATUS_OPTIONS = ["pending", "confirmed", "dismissed", "archived"];
const RELATION_TYPE_OPTIONS = ["same_as", "related_to", "employed_by", "parent_of", "child_of", "located_in", "affiliated_with"];

export function EntityDetail() {
  const { id } = useParams<{ id: string }>();
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const isNewMode = id === "new";
  const [entity, setEntity] = useState<Entity | null>(null);
  const [linkedArchive, setLinkedArchive] = useState<ArchiveItem[]>([]);
  const [linkedEvents, setLinkedEvents] = useState<Event[]>([]);
  const [outgoingRels, setOutgoingRels] = useState<EntityRelationship[]>([]);
  const [incomingRels, setIncomingRels] = useState<EntityRelationship[]>([]);
  const [availableArchive, setAvailableArchive] = useState<ArchiveItem[]>([]);
  const [availableEvents, setAvailableEvents] = useState<Event[]>([]);
  const [availableEntities, setAvailableEntities] = useState<Entity[]>([]);
  const [entityNameMap, setEntityNameMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(isNewMode);
  const [denied, setDenied] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    entity_type: "PERSON",
    name: "",
    description: "",
    status: "pending",
    confidence: 0.5,
  });

  // Linking state
  const [linkArchiveError, setLinkArchiveError] = useState<string | null>(null);
  const [linkArchiveId, setLinkArchiveId] = useState<string | null>(null);
  const [linkEventError, setLinkEventError] = useState<string | null>(null);
  const [linkEventId, setLinkEventId] = useState<string | null>(null);

  // Relationship state
  const [relError, setRelError] = useState<string | null>(null);
  const [selectedRelatedEntity, setSelectedRelatedEntity] = useState<string>("");
  const [selectedRelationType, setSelectedRelationType] = useState<string>("related_to");
  const [selectedRelationConfidence, setSelectedRelationConfidence] = useState<number>(0.5);
  const [creatingRel, setCreatingRel] = useState(false);

  const loadEntity = useCallback(async () => {
    if (!token || !id || isNewMode) return;
    setLoading(true);
    setError(null);
    setDenied(false);
    try {
      const ent = await getEntity(token, id);
      setEntity(ent);
      setFormData({
        entity_type: ent.entity_type,
        name: ent.name,
        description: ent.description || "",
        status: ent.status,
        confidence: ent.confidence,
      });
    } catch (e) {
      const exc = e as ApiException;
      if (exc.status === 403) {
        setDenied(true);
      } else if (exc.status === 404) {
        setError("الكيان غير موجود");
      } else {
        setError(exc.message || "خطأ في التحميل");
      }
    } finally {
      setLoading(false);
    }
  }, [token, id, isNewMode]);

  const loadRelationships = useCallback(async () => {
    if (!token || !id || isNewMode) return;
    try {
      const rels = await getEntityRelationships(token, id);
      setOutgoingRels(rels.outgoing);
      setIncomingRels(rels.incoming);
    } catch (e) {
      // Silently fail on relationships load
    }
  }, [token, id, isNewMode]);

  const loadRelatedData = useCallback(async () => {
    if (!token) return;
    try {
      const archive = await searchArchive(token);
      setAvailableArchive(archive);
      const events = await listEvents(token, 500);
      setAvailableEvents(events);
      const entities = await listEntities(token, 500);
      setAvailableEntities(entities);
      // Build entity name map for display
      const nameMap: Record<string, string> = {};
      entities.forEach((ent) => {
        nameMap[ent.id] = ent.name;
      });
      setEntityNameMap(nameMap);
    } catch (e) {
      // Silently fail on data load
    }
  }, [token]);

  useEffect(() => {
    void loadEntity();
    void loadRelatedData();
  }, [loadEntity, loadRelatedData]);

  useEffect(() => {
    void loadRelationships();
  }, [loadRelationships]);

  const handleSave = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      if (isNewMode) {
        const created = await createEntity(token, {
          entity_type: formData.entity_type,
          name: formData.name,
          description: formData.description || undefined,
          status: formData.status,
          confidence: formData.confidence,
        });
        navigate(`/entities/${created.id}`);
      } else if (id && entity) {
        const updated = await updateEntity(token, id, {
          name: formData.name,
          description: formData.description || null,
          status: formData.status,
          confidence: formData.confidence,
        });
        setEntity(updated);
        setEditing(false);
      }
    } catch (e) {
      const exc = e as ApiException;
      setError(exc.message || "خطأ في الحفظ");
    } finally {
      setLoading(false);
    }
  }, [token, id, entity, formData, isNewMode, navigate]);

  const handleLinkArchive = useCallback(
    async (archiveId: string) => {
      if (!token || !id) return;
      setLinkArchiveError(null);
      setLinkArchiveId(archiveId);
      try {
        await linkArchiveToEntity(token, id, archiveId);
        const linkedItem = availableArchive.find((item) => item.id === archiveId);
        if (linkedItem) {
          setLinkedArchive((prev) => [...prev, linkedItem]);
        }
      } catch (e) {
        const exc = e as ApiException;
        if (exc.status === 409) {
          setLinkArchiveError("عنصر الأرشيف مرتبط بالفعل");
        } else if (exc.status === 404) {
          setLinkArchiveError("الكيان أو عنصر الأرشيف غير موجود");
        } else {
          setLinkArchiveError(exc.message || "خطأ في الربط");
        }
      } finally {
        setLinkArchiveId(null);
      }
    },
    [token, id, availableArchive],
  );

  const handleUnlinkArchive = useCallback(
    async (archiveId: string) => {
      if (!token || !id) return;
      try {
        await unlinkArchiveFromEntity(token, id, archiveId);
        setLinkedArchive((prev) => prev.filter((item) => item.id !== archiveId));
      } catch (e) {
        setLinkArchiveError("خطأ في فك الربط");
      }
    },
    [token, id],
  );

  const handleLinkEvent = useCallback(
    async (eventId: string) => {
      if (!token || !id) return;
      setLinkEventError(null);
      setLinkEventId(eventId);
      try {
        await linkEntityToEvent(token, id, eventId);
        const linkedItem = availableEvents.find((item) => item.id === eventId);
        if (linkedItem) {
          setLinkedEvents((prev) => [...prev, linkedItem]);
        }
      } catch (e) {
        const exc = e as ApiException;
        if (exc.status === 409) {
          setLinkEventError("الحدث مرتبط بالفعل");
        } else if (exc.status === 404) {
          setLinkEventError("الكيان أو الحدث غير موجود");
        } else {
          setLinkEventError(exc.message || "خطأ في الربط");
        }
      } finally {
        setLinkEventId(null);
      }
    },
    [token, id, availableEvents],
  );

  const handleUnlinkEvent = useCallback(
    async (eventId: string) => {
      if (!token || !id) return;
      try {
        await unlinkEntityFromEvent(token, id, eventId);
        setLinkedEvents((prev) => prev.filter((item) => item.id !== eventId));
      } catch (e) {
        setLinkEventError("خطأ في فك الربط");
      }
    },
    [token, id],
  );

  const handleCreateRelationship = useCallback(async () => {
    if (!token || !id || !selectedRelatedEntity) return;
    setRelError(null);
    setCreatingRel(true);
    try {
      await createRelationship(token, id, selectedRelatedEntity, {
        relation_type: selectedRelationType,
        confidence: selectedRelationConfidence,
      });
      // Clear selection
      setSelectedRelatedEntity("");
      setSelectedRelationType("related_to");
      setSelectedRelationConfidence(0.5);
      // Refresh relationships
      const rels = await getEntityRelationships(token, id);
      setOutgoingRels(rels.outgoing);
      setIncomingRels(rels.incoming);
    } catch (e) {
      const exc = e as ApiException;
      if (exc.status === 409) {
        setRelError("العلاقة موجودة بالفعل");
      } else {
        setRelError(exc.message || "خطأ في إنشاء العلاقة");
      }
    } finally {
      setCreatingRel(false);
    }
  }, [token, id, selectedRelatedEntity, selectedRelationType, selectedRelationConfidence]);

  const handleDeleteRelationship = useCallback(
    async (relId: string) => {
      if (!token || !id) return;
      try {
        await deleteRelationship(token, relId);
        // Refresh relationships to maintain consistency
        const rels = await getEntityRelationships(token, id);
        setOutgoingRels(rels.outgoing);
        setIncomingRels(rels.incoming);
      } catch (e) {
        setRelError("خطأ في حذف العلاقة");
      }
    },
    [token, id],
  );

  const formatDate = (dateStr: string): string => {
    try {
      const d = new Date(dateStr);
      return d.toISOString().slice(0, 19).replace("T", " ");
    } catch {
      return dateStr;
    }
  };

  if (denied) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
          <div className="flex items-center gap-3">
            <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
            <span className="text-slate-500">·</span>
            <span className="text-sm text-slate-400">الكيانات</span>
          </div>
          <Link to="/entities" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
            ← قائمة الكيانات
          </Link>
        </header>
        <Card>
          <p className="text-crit font-mono text-sm">لا توجد صلاحيات لعرض هذا الكيان.</p>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <p className="text-slate-400">جارٍ التحميل...</p>
      </div>
    );
  }

  if (!isNewMode && !entity && error) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <Card>
          <p className="text-crit font-mono text-sm">{error}</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
          <span className="text-slate-500">·</span>
          <span className="text-sm text-slate-400">{isNewMode ? "كيان جديد" : entity?.name}</span>
        </div>
        <div className="flex gap-2">
          {!isNewMode && user?.permission_codes?.includes("entity:update") && (
            <button
              onClick={() => setEditing(!editing)}
              className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass"
            >
              {editing ? "إلغاء" : "تعديل"}
            </button>
          )}
          <Link to="/entities" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
            ← قائمة الكيانات
          </Link>
        </div>
      </header>

      {error && <p className="mb-4 font-mono text-sm text-crit">خطأ: {error}</p>}

      {/* Entity Info Card */}
      <Card>
        <Eyebrow>معلومات الكيان</Eyebrow>
        <div className="mt-4 space-y-4">
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">نوع الكيان</label>
            {editing ? (
              <select
                value={formData.entity_type}
                onChange={(e) => setFormData({ ...formData, entity_type: e.target.value })}
                disabled={!isNewMode}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none disabled:opacity-50"
              >
                {ENTITY_TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-sm text-slate-100">{entity?.entity_type}</p>
            )}
          </div>

          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">الاسم</label>
            {editing ? (
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              />
            ) : (
              <p className="text-sm text-slate-100">{entity?.name}</p>
            )}
          </div>

          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">الوصف</label>
            {editing ? (
              <textarea
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
                rows={3}
              />
            ) : (
              <p className="text-sm text-slate-100">{entity?.description || "—"}</p>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">الحالة</label>
              {editing ? (
                <select
                  value={formData.status}
                  onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                  className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              ) : (
                <Badge tone={entity?.status === "confirmed" ? "brass" : "neutral"}>{entity?.status}</Badge>
              )}
            </div>

            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">الثقة</label>
              {editing ? (
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={formData.confidence}
                  onChange={(e) => setFormData({ ...formData, confidence: parseFloat(e.target.value) })}
                  className="w-full"
                />
              ) : null}
              <p className="text-sm text-slate-100">{(formData.confidence * 100).toFixed(0)}%</p>
            </div>
          </div>

          {entity && (
            <div className="border-t border-line pt-3 space-y-1 text-xs text-slate-500">
              <p>أنشئ: {formatDate(entity.created_at)}</p>
              {entity.created_by && <p>من قبل: {entity.created_by}</p>}
              {entity.updated_at && entity.updated_at !== entity.created_at && (
                <>
                  <p>عُدّل: {formatDate(entity.updated_at)}</p>
                  {entity.updated_by && <p>من قبل: {entity.updated_by}</p>}
                </>
              )}
            </div>
          )}

          {editing && (
            <div className="flex gap-2 border-t border-line pt-4">
              <button
                onClick={handleSave}
                disabled={loading}
                className="flex-1 rounded bg-brass px-4 py-2 text-sm font-medium text-black hover:bg-brass/90 disabled:opacity-50"
              >
                {loading ? "جارٍ الحفظ..." : "حفظ"}
              </button>
            </div>
          )}
        </div>
      </Card>

      {/* Linked Archive */}
      {!isNewMode && (
        <Card className="mt-6">
          <Eyebrow>عناصر الأرشيف المرتبطة</Eyebrow>
          <div className="mt-4">
            {linkArchiveError && <p className="mb-4 text-sm text-crit">خطأ: {linkArchiveError}</p>}

            {linkedArchive.length > 0 && (
              <div className="mb-6 space-y-2">
                {linkedArchive.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between rounded border border-line p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-slate-100 truncate">{item.title || item.url}</p>
                      <p className="text-xs text-slate-500">{formatDate(item.collected_at)}</p>
                    </div>
                    {user?.permission_codes?.includes("entity:link:archive") && (
                      <button
                        onClick={() => handleUnlinkArchive(item.id)}
                        className="ml-2 text-xs text-crit hover:text-crit/90"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {user?.permission_codes?.includes("entity:link:archive") && (
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-2">إضافة عنصر أرشيف</label>
                <div className="space-y-2">
                  {availableArchive
                    .filter((item) => !linkedArchive.find((l) => l.id === item.id))
                    .slice(0, 10)
                    .map((item) => (
                      <button
                        key={item.id}
                        onClick={() => handleLinkArchive(item.id)}
                        disabled={linkArchiveId === item.id}
                        className="w-full text-left rounded border border-line p-3 text-sm hover:border-brass hover:bg-slate-900/50 disabled:opacity-50"
                      >
                        {item.title || item.url}
                      </button>
                    ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Linked Events */}
      {!isNewMode && (
        <Card className="mt-6">
          <Eyebrow>الأحداث المرتبطة</Eyebrow>
          <div className="mt-4">
            {linkEventError && <p className="mb-4 text-sm text-crit">خطأ: {linkEventError}</p>}

            {linkedEvents.length > 0 && (
              <div className="mb-6 space-y-2">
                {linkedEvents.map((evt) => (
                  <div
                    key={evt.id}
                    className="flex items-center justify-between rounded border border-line p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-slate-100 truncate">{evt.title}</p>
                      <p className="text-xs text-slate-500">{formatDate(evt.occurred_at)}</p>
                    </div>
                    {user?.permission_codes?.includes("entity:link:event") && (
                      <button
                        onClick={() => handleUnlinkEvent(evt.id)}
                        className="ml-2 text-xs text-crit hover:text-crit/90"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {user?.permission_codes?.includes("entity:link:event") && (
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-2">إضافة حدث</label>
                <div className="space-y-2">
                  {availableEvents
                    .filter((evt) => !linkedEvents.find((l) => l.id === evt.id))
                    .slice(0, 10)
                    .map((evt) => (
                      <button
                        key={evt.id}
                        onClick={() => handleLinkEvent(evt.id)}
                        disabled={linkEventId === evt.id}
                        className="w-full text-left rounded border border-line p-3 text-sm hover:border-brass hover:bg-slate-900/50 disabled:opacity-50"
                      >
                        {evt.title}
                      </button>
                    ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Relationships */}
      {!isNewMode && (
        <Card className="mt-6">
          <Eyebrow>العلاقات</Eyebrow>
          <div className="mt-4">
            {relError && <p className="mb-4 text-sm text-crit">خطأ: {relError}</p>}

            {(outgoingRels.length > 0 || incomingRels.length > 0) && (
              <div className="mb-6 space-y-3">
                {outgoingRels.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-slate-400 mb-2">علاقات خارجة:</p>
                    {outgoingRels.map((rel) => (
                      <div key={rel.id} className="flex items-center justify-between rounded border border-line p-3 mb-2">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-slate-100">{rel.relation_type}</p>
                          <p className="text-xs text-slate-500">
                            إلى: {entityNameMap[rel.to_entity_id] || rel.to_entity_id.slice(0, 8)}... ({(rel.confidence * 100).toFixed(0)}%)
                          </p>
                        </div>
                        {user?.permission_codes?.includes("entity:relate") && (
                          <button
                            onClick={() => handleDeleteRelationship(rel.id)}
                            className="ml-2 text-xs text-crit hover:text-crit/90"
                          >
                            ✕
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {incomingRels.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-slate-400 mb-2">علاقات واردة:</p>
                    {incomingRels.map((rel) => (
                      <div key={rel.id} className="flex items-center justify-between rounded border border-line p-3 mb-2">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-slate-100">{rel.relation_type}</p>
                          <p className="text-xs text-slate-500">
                            من: {entityNameMap[rel.from_entity_id] || rel.from_entity_id.slice(0, 8)}... ({(rel.confidence * 100).toFixed(0)}%)
                          </p>
                        </div>
                        {user?.permission_codes?.includes("entity:relate") && (
                          <button
                            onClick={() => handleDeleteRelationship(rel.id)}
                            className="ml-2 text-xs text-crit hover:text-crit/90"
                          >
                            ✕
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {user?.permission_codes?.includes("entity:relate") && (
              <div className="border-t border-line pt-4">
                <label className="block text-[11px] font-medium text-slate-400 mb-3">إنشاء علاقة</label>
                <div className="space-y-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-400 mb-1">الكيان المرتبط</label>
                    <select
                      value={selectedRelatedEntity}
                      onChange={(e) => setSelectedRelatedEntity(e.target.value)}
                      className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
                    >
                      <option value="">-- اختر كيان --</option>
                      {availableEntities
                        .filter((ent) => ent.id !== id)
                        .map((ent) => (
                          <option key={ent.id} value={ent.id}>
                            {ent.name}
                          </option>
                        ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-slate-400 mb-1">نوع العلاقة</label>
                    <select
                      value={selectedRelationType}
                      onChange={(e) => setSelectedRelationType(e.target.value)}
                      className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
                    >
                      {RELATION_TYPE_OPTIONS.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-slate-400 mb-1">الثقة</label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={selectedRelationConfidence}
                      onChange={(e) => setSelectedRelationConfidence(parseFloat(e.target.value))}
                      className="w-full"
                    />
                    <p className="text-xs text-slate-500">الثقة: {(selectedRelationConfidence * 100).toFixed(0)}%</p>
                  </div>

                  <button
                    onClick={handleCreateRelationship}
                    disabled={creatingRel || !selectedRelatedEntity}
                    className="w-full rounded bg-brass px-4 py-2 text-sm font-medium text-black hover:bg-brass/90 disabled:opacity-50"
                  >
                    {creatingRel ? "جارٍ الإنشاء..." : "إنشاء علاقة"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
