import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { listEntities, type Entity, type ApiException } from "../lib/api";
import { Card, Eyebrow, Badge } from "../components/ui";

const ENTITY_TYPE_OPTIONS = ["PERSON", "ORGANIZATION", "LOCATION", "VEHICLE", "FACILITY", "WEAPON", "EVENT"];
const STATUS_OPTIONS = ["pending", "confirmed", "dismissed", "archived"];

export function Entities() {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [denied, setDenied] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    setDenied(false);
    try {
      const result = await listEntities(
        token,
        100,
        0,
        entityTypeFilter || undefined,
        statusFilter || undefined,
      );
      setEntities(result);
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
  }, [token, entityTypeFilter, statusFilter]);

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

  const getStatusTone = (status: string): "neutral" | "brass" | "steel" | "muted" => {
    switch (status) {
      case "pending":
        return "neutral";
      case "confirmed":
        return "brass";
      case "dismissed":
        return "muted";
      case "archived":
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
            <span className="text-sm text-slate-400">الكيانات</span>
          </div>
          <Link to="/" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
            ← لوحة التشغيل
          </Link>
        </header>
        <Card>
          <p className="text-crit font-mono text-sm">لا توجد صلاحيات لعرض الكيانات.</p>
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
          <span className="text-sm text-slate-400">الكيانات</span>
        </div>
        <div className="flex gap-2">
          {user?.permission_codes?.includes("entity:create") && (
            <button
              onClick={() => navigate("/entities/new")}
              className="rounded border border-brass px-3 py-1.5 text-[12px] font-medium text-brass hover:bg-brass/10"
            >
              + كيان جديد
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
              <label className="block text-[11px] font-medium text-slate-400 mb-1">نوع الكيان</label>
              <select
                value={entityTypeFilter}
                onChange={(e) => setEntityTypeFilter(e.target.value)}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              >
                <option value="">الكل</option>
                {ENTITY_TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
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
          </div>
        </div>

        {loading && <p className="text-sm text-slate-400">جارٍ التحميل...</p>}

        {!loading && entities.length === 0 && (
          <p className="text-sm text-slate-500">لا توجد كيانات.</p>
        )}

        {!loading && entities.length > 0 && (
          <div className="space-y-2 border-t border-line pt-6">
            {entities.map((entity) => (
              <Link
                key={entity.id}
                to={`/entities/${entity.id}`}
                className="block rounded border border-line p-4 hover:border-brass hover:bg-slate-900/50 transition"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-slate-100">{entity.name}</p>
                    <p className="text-xs text-slate-500 mt-1">{entity.entity_type}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 justify-end">
                    <Badge tone={getStatusTone(entity.status)}>{entity.status}</Badge>
                    <span className="text-xs text-slate-400 tabular-nums">
                      {(entity.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
                <p className="text-xs text-slate-500 mt-2">{formatDate(entity.created_at)}</p>
              </Link>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
