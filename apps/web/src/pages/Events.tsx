import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { listEvents, type Event, type ApiException } from "../lib/api";
import { Card, Eyebrow, Badge } from "../components/ui";

const STATUS_OPTIONS = ["pending", "confirmed", "dismissed", "closed"];
const SEVERITY_OPTIONS = ["A", "B", "C", "D", "E", "F"];

export function Events() {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [denied, setDenied] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    setDenied(false);
    try {
      const result = await listEvents(token, 100, 0, statusFilter || undefined, severityFilter || undefined);
      setEvents(result);
    } catch (e) {
      const exc = e as ApiException;
      if (exc.status === 403) {
        setDenied(true);
      } else {
        setError(exc.message || "خطأ في التحميل");
      }
    } finally {
      setLoading(false);
    }
  }, [token, statusFilter, severityFilter]);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 30000);
    return () => clearInterval(id);
  }, [load]);

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

  if (denied) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
          <div className="flex items-center gap-3">
            <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
            <span className="text-slate-500">·</span>
            <span className="text-sm text-slate-400">الأحداث</span>
          </div>
          <Link to="/" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
            ← لوحة التشغيل
          </Link>
        </header>
        <Card>
          <p className="text-crit font-mono text-sm">لا توجد صلاحيات لعرض الأحداث.</p>
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
          <span className="text-sm text-slate-400">الأحداث</span>
        </div>
        <div className="flex gap-2">
          {user?.permission_codes?.includes("event:create") && (
            <button
              onClick={() => navigate("/events/new")}
              className="rounded border border-brass px-3 py-1.5 text-[12px] font-medium text-brass hover:bg-brass/10"
            >
              + حدث جديد
            </button>
          )}
          <Link to="/" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
            ← لوحة التشغيل
          </Link>
        </div>
      </header>

      {error && <p className="mb-4 font-mono text-sm text-crit">خطأ: {error}</p>}

      <Card>
        <div className="mb-6 space-y-3">
          <Eyebrow>تصفية</Eyebrow>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">الحالة</label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              >
                <option value="">الكل</option>
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
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              >
                <option value="">الكل</option>
                {SEVERITY_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <Eyebrow>
          الأحداث ({events.length})
        </Eyebrow>

        {loading && !events.length && (
          <p className="text-sm text-slate-500">جارٍ التحميل…</p>
        )}

        {!loading && events.length === 0 && (
          <p className="text-sm text-slate-500">لا توجد أحداث.</p>
        )}

        {events.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-[12.5px]">
              <thead>
                <tr className="border-b border-line text-right font-mono text-[10.5px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 font-medium">العنوان</th>
                  <th className="py-2 font-medium">الحالة</th>
                  <th className="py-2 font-medium">الشدة</th>
                  <th className="py-2 font-medium">الثقة</th>
                  <th className="py-2 font-medium">تاريخ الحدوث</th>
                  <th className="py-2 font-medium">الإنشاء</th>
                  <th className="py-2 font-medium">الإجراء</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr
                    key={event.id}
                    className="border-b border-line/50 cursor-pointer hover:bg-slate-900/50"
                    onClick={() => navigate(`/events/${event.id}`)}
                  >
                    <td className="py-2.5 text-slate-200">{event.title}</td>
                    <td className="py-2.5">
                      <Badge tone={getStatusTone(event.status)}>{event.status}</Badge>
                    </td>
                    <td className="py-2.5">
                      <Badge tone={getSeverityTone(event.severity)}>{event.severity}</Badge>
                    </td>
                    <td className="py-2.5 text-slate-400">{(event.confidence * 100).toFixed(0)}%</td>
                    <td className="py-2.5 font-mono text-[11px] text-slate-500">
                      {formatDate(event.occurred_at)}
                    </td>
                    <td className="py-2.5 font-mono text-[11px] text-slate-500">
                      {formatDate(event.created_at)}
                    </td>
                    <td className="py-2.5 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/events/${event.id}`);
                        }}
                        className="text-brass-soft hover:text-brass text-[12px]"
                      >
                        عرض →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
