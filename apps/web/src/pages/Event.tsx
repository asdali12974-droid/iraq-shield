import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  getEvent,
  updateEvent,
  createEvent,
  linkArchiveToEvent,
  unlinkArchiveFromEvent,
  searchArchive,
  type Event,
  type ArchiveItem,
  type ApiException,
} from "../lib/api";
import { Card, Eyebrow, Badge } from "../components/ui";

const STATUS_OPTIONS = ["pending", "confirmed", "dismissed", "closed"];
const SEVERITY_OPTIONS = ["A", "B", "C", "D", "E", "F"];

export function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const isNewMode = id === "new";
  const [event, setEvent] = useState<Event | null>(null);
  const [linkedArchive, setLinkedArchive] = useState<ArchiveItem[]>([]);
  const [availableArchive, setAvailableArchive] = useState<ArchiveItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(isNewMode);
  const [denied, setDenied] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    title: "",
    description: "",
    status: "pending",
    severity: "C",
    confidence: 0.5,
    occurred_at: new Date().toISOString().slice(0, 16),
  });

  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkingArchiveId, setLinkingArchiveId] = useState<string | null>(null);

  const loadEvent = useCallback(async () => {
    if (!token || !id || isNewMode) return;
    setLoading(true);
    setError(null);
    setDenied(false);
    try {
      const evt = await getEvent(token, id);
      setEvent(evt);
      setFormData({
        title: evt.title,
        description: evt.description || "",
        status: evt.status,
        severity: evt.severity,
        confidence: evt.confidence,
        occurred_at: evt.occurred_at.slice(0, 16),
      });
    } catch (e) {
      const exc = e as ApiException;
      if (exc.status === 403) {
        setDenied(true);
      } else if (exc.status === 404) {
        setError("الحدث غير موجود");
      } else {
        setError(exc.message || "خطأ في التحميل");
      }
    } finally {
      setLoading(false);
    }
  }, [token, id, isNewMode]);

  const loadArchive = useCallback(async () => {
    if (!token) return;
    try {
      // Fetch all current archive items for linking
      const items = await searchArchive(token);
      setAvailableArchive(items);
    } catch (e) {
      // Silently fail on archive load
    }
  }, [token]);

  useEffect(() => {
    void loadEvent();
    void loadArchive();
  }, [loadEvent, loadArchive]);

  const handleSave = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      if (isNewMode) {
        const created = await createEvent(token, {
          title: formData.title,
          description: formData.description || undefined,
          occurred_at: formData.occurred_at,
          status: formData.status,
          severity: formData.severity,
          confidence: formData.confidence,
        });
        navigate(`/events/${created.id}`);
      } else if (id && event) {
        const updated = await updateEvent(token, id, {
          title: formData.title,
          description: formData.description || null,
          occurred_at: formData.occurred_at,
          status: formData.status,
          severity: formData.severity,
          confidence: formData.confidence,
        });
        setEvent(updated);
        setEditing(false);
      }
    } catch (e) {
      const exc = e as ApiException;
      setError(exc.message || "خطأ في الحفظ");
    } finally {
      setLoading(false);
    }
  }, [token, id, event, formData, isNewMode, navigate]);

  const handleLinkArchive = useCallback(
    async (archiveId: string) => {
      if (!token || !id) return;
      setLinkError(null);
      setLinkingArchiveId(archiveId);
      try {
        await linkArchiveToEvent(token, id, archiveId);
        // Add the linked item to the state (find it in availableArchive)
        const linkedItem = availableArchive.find((item) => item.id === archiveId);
        if (linkedItem) {
          setLinkedArchive((prev) => [...prev, linkedItem]);
        }
      } catch (e) {
        const exc = e as ApiException;
        if (exc.status === 409) {
          setLinkError("عنصر الأرشيف مرتبط بالفعل");
        } else if (exc.status === 404) {
          setLinkError("الحدث أو عنصر الأرشيف غير موجود");
        } else {
          setLinkError(exc.message || "خطأ في الربط");
        }
      } finally {
        setLinkingArchiveId(null);
      }
    },
    [token, id, availableArchive],
  );

  const handleUnlinkArchive = useCallback(
    async (archiveId: string) => {
      if (!token || !id) return;
      setLinkError(null);
      try {
        await unlinkArchiveFromEvent(token, id, archiveId);
        setLinkedArchive((prev) => prev.filter((item) => item.id !== archiveId));
      } catch (e) {
        const exc = e as ApiException;
        setLinkError(exc.message || "خطأ في فك الربط");
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

  const getSeverityTone = (severity: string): "neutral" | "brass" | "steel" | "muted" => {
    switch (severity) {
      case "A":
        return "brass";
      case "B":
      case "C":
        return "steel";
      default:
        return "muted";
    }
  };

  const getStatusTone = (status: string): "neutral" | "brass" | "steel" | "muted" => {
    switch (status) {
      case "pending":
        return "neutral";
      case "confirmed":
        return "brass";
      case "dismissed":
        return "muted";
      case "closed":
        return "steel";
      default:
        return "muted";
    }
  };

  if (denied && !isNewMode) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
          <div className="flex items-center gap-3">
            <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
          </div>
          <Link to="/events" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
            ← العودة إلى الأحداث
          </Link>
        </header>
        <Card>
          <p className="text-crit font-mono text-sm">لا توجد صلاحيات لعرض هذا الحدث.</p>
        </Card>
      </div>
    );
  }

  if (loading && !event && !isNewMode) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <Card>
          <p className="text-sm text-slate-500">جارٍ التحميل…</p>
        </Card>
      </div>
    );
  }

  if (error && !event && !isNewMode) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <Card>
          <p className="text-crit font-mono text-sm">خطأ: {error}</p>
        </Card>
      </div>
    );
  }

  if (!event && !isNewMode) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <Card>
          <p className="text-sm text-slate-500">لم يتم العثور على الحدث.</p>
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
          <span className="text-sm text-slate-400">{isNewMode ? "حدث جديد" : event?.title}</span>
        </div>
        <Link to="/events" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
          ← العودة إلى الأحداث
        </Link>
      </header>

      {error && <p className="mb-4 font-mono text-sm text-crit">خطأ: {error}</p>}

      <Card>
        <Eyebrow>{isNewMode ? "إنشاء حدث جديد" : "معلومات الحدث"}</Eyebrow>
        {!editing && !isNewMode && event ? (
          <div className="space-y-4">
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">العنوان</label>
              <p className="text-slate-200">{event.title}</p>
            </div>
            {event.description && (
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">الوصف</label>
                <p className="text-slate-200 whitespace-pre-wrap">{event.description}</p>
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">الحالة</label>
                <Badge tone={getStatusTone(event.status)}>{event.status}</Badge>
              </div>
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">الشدة</label>
                <Badge tone={getSeverityTone(event.severity)}>{event.severity}</Badge>
              </div>
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">الثقة</label>
                <p className="text-slate-200">{(event.confidence * 100).toFixed(0)}%</p>
              </div>
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">تاريخ الحدوث</label>
                <p className="text-slate-200 font-mono text-[11px]">{formatDate(event.occurred_at)}</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 text-[11px]">
              <div>
                <label className="block font-medium text-slate-400 mb-1">تم الإنشاء</label>
                <p className="text-slate-400 font-mono">{formatDate(event.created_at)}</p>
              </div>
              <div>
                <label className="block font-medium text-slate-400 mb-1">آخر تحديث</label>
                <p className="text-slate-400 font-mono">{formatDate(event.updated_at)}</p>
              </div>
            </div>
            {user?.permission_codes?.includes("event:update") && (
              <button
                onClick={() => setEditing(true)}
                className="rounded border border-brass px-3 py-2 text-sm font-medium text-brass hover:bg-brass/10"
              >
                تعديل
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">العنوان *</label>
              <input
                type="text"
                value={formData.title}
                onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                placeholder="عنوان الحدث"
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">الوصف</label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                rows={3}
                placeholder="وصف الحدث (اختياري)"
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">تاريخ الحدوث *</label>
              <input
                type="datetime-local"
                value={formData.occurred_at}
                onChange={(e) => setFormData({ ...formData, occurred_at: e.target.value })}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">الحالة</label>
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
              </div>
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">الشدة</label>
                <select
                  value={formData.severity}
                  onChange={(e) => setFormData({ ...formData, severity: e.target.value })}
                  className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
                >
                  {SEVERITY_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">الثقة (0-1)</label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.1"
                  value={formData.confidence}
                  onChange={(e) => setFormData({ ...formData, confidence: parseFloat(e.target.value) })}
                  className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => void handleSave()}
                disabled={loading || !formData.title}
                className="rounded border border-brass px-3 py-2 text-sm font-medium text-brass hover:bg-brass/10 disabled:opacity-50 disabled:border-slate-600 disabled:text-slate-600"
              >
                {isNewMode ? "إنشاء" : "حفظ"}
              </button>
              <button
                onClick={() => {
                  if (isNewMode) {
                    navigate("/events");
                  } else {
                    setEditing(false);
                    if (event) {
                      setFormData({
                        title: event.title,
                        description: event.description || "",
                        status: event.status,
                        severity: event.severity,
                        confidence: event.confidence,
                        occurred_at: event.occurred_at.slice(0, 16),
                      });
                    }
                  }
                }}
                className="rounded border border-line px-3 py-2 text-sm font-medium text-slate-400 hover:border-slate-300"
              >
                إلغاء
              </button>
            </div>
          </div>
        )}
      </Card>

      {!isNewMode && user?.permission_codes?.includes("event:link") && (
        <Card>
          <Eyebrow>ربط عناصر الأرشيف</Eyebrow>
          {linkError && <p className="mb-4 text-sm text-crit">خطأ: {linkError}</p>}
          <div className="space-y-4">
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-2">عناصر أرشيفية متاحة</label>
              <div className="max-h-[300px] overflow-y-auto border border-line/50 rounded">
                {availableArchive.length === 0 ? (
                  <p className="p-3 text-sm text-slate-500">لا توجد عناصر أرشيفية.</p>
                ) : (
                  <div className="divide-y divide-line/50">
                    {availableArchive.map((item) => (
                      <div key={item.id} className="p-3 flex items-start justify-between gap-2 hover:bg-slate-900/30">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-200 truncate">{item.title || "—"}</p>
                          <p className="text-[11px] text-slate-500 truncate">{item.url}</p>
                        </div>
                        <button
                          onClick={() => void handleLinkArchive(item.id)}
                          disabled={linkingArchiveId === item.id || loading}
                          className="text-brass-soft hover:text-brass text-[12px] whitespace-nowrap px-2 py-1 disabled:opacity-50"
                        >
                          ربط
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </Card>
      )}

      {!isNewMode && linkedArchive.length > 0 && (
        <Card>
          <Eyebrow>عناصر أرشيفية مرتبطة ({linkedArchive.length})</Eyebrow>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-[12px]">
              <thead>
                <tr className="border-b border-line text-right font-mono text-[10px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 font-medium">العنوان</th>
                  <th className="py-2 font-medium">تم الجمع</th>
                  {user?.permission_codes?.includes("event:link") && <th className="py-2 font-medium">الإجراء</th>}
                </tr>
              </thead>
              <tbody>
                {linkedArchive.map((item) => (
                  <tr key={item.id} className="border-b border-line/50">
                    <td className="py-2 text-slate-200 truncate">{item.title || "—"}</td>
                    <td className="py-2 text-slate-500 font-mono text-[11px]">{formatDate(item.collected_at)}</td>
                    {user?.permission_codes?.includes("event:link") && (
                      <td className="py-2">
                        <button
                          onClick={() => void handleUnlinkArchive(item.id)}
                          className="text-slate-500 hover:text-crit text-[11px]"
                        >
                          فك الربط
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
