import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  fetchSources,
  fetchSourcesDashboard,
  type Source,
  type SourcesDashboard,
} from "../lib/api";
import { Card, Eyebrow, Badge } from "../components/ui";

const HEALTH_TONE: Record<string, string> = {
  healthy: "text-ok",
  degraded: "text-warn",
  failed: "text-crit",
  pending: "text-slate-400",
  disabled: "text-slate-500",
};

const TYPE_TONE: Record<string, string> = {
  RSS: "border-steel/50 text-steel-soft",
  WEBSITE: "border-brass/50 text-brass-soft",
  TELEGRAM_PUBLIC: "border-sky-500/40 text-sky-300",
  TELEGRAM_PUBLIC_WEB: "border-sky-500/40 text-sky-300",
};

function Tile({ label, value, tone = "" }: { label: string; value: number; tone?: string }) {
  return (
    <Card className="!p-4">
      <div className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-slate-500">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
    </Card>
  );
}

export function Sources() {
  const { token } = useAuth();
  const [dash, setDash] = useState<SourcesDashboard | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [d, s] = await Promise.all([
        fetchSourcesDashboard(token),
        fetchSources(token),
      ]);
      setDash(d);
      setSources(s);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [token]);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 10000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
          <span className="text-slate-500">·</span>
          <span className="text-sm text-slate-400">المصادر</span>
        </div>
        <Link to="/" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
          ← لوحة التشغيل
        </Link>
      </header>

      {error && <p className="mb-4 font-mono text-sm text-crit">تعذّر الوصول: {error}</p>}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <Tile label="الإجمالي" value={dash?.total ?? 0} />
        <Tile label="مفعّلة" value={dash?.active ?? 0} tone="text-steel-soft" />
        <Tile label="معطّلة" value={dash?.disabled ?? 0} tone="text-slate-400" />
        <Tile label="سليمة" value={dash?.healthy ?? 0} tone="text-ok" />
        <Tile label="متدهورة" value={dash?.degraded ?? 0} tone="text-warn" />
        <Tile label="فاشلة" value={dash?.failed ?? 0} tone="text-crit" />
        <Tile label="عناصر الأرشيف" value={dash?.archive_items ?? 0} tone="text-brass-soft" />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <Eyebrow>المصادر</Eyebrow>
            {sources.length === 0 && (
              <p className="text-sm text-slate-500">
                لا توجد مصادر بعد. تُضاف المصادر عبر الـ API (سجلّ المصادر).
              </p>
            )}
            {sources.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-[13px]">
                  <thead>
                    <tr className="border-b border-line text-right font-mono text-[10.5px] uppercase tracking-wider text-slate-500">
                      <th className="py-2 font-medium">الاسم</th>
                      <th className="py-2 font-medium">النوع</th>
                      <th className="py-2 font-medium">الحالة</th>
                      <th className="py-2 font-medium">نجاح</th>
                      <th className="py-2 font-medium">جولات</th>
                      <th className="py-2 font-medium">زمن</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sources.map((s) => (
                      <tr key={s.id} className="border-b border-line/50">
                        <td className="py-2.5">
                          <Link to={`/sources/${s.id}`} className="text-slate-200 hover:text-brass-soft">
                            {s.name}
                          </Link>
                        </td>
                        <td className="py-2.5">
                          <span className={`rounded border px-2 py-0.5 font-mono text-[10.5px] ${TYPE_TONE[s.source_type] ?? "border-line text-slate-400"}`}>
                            {s.source_type}
                          </span>
                        </td>
                        <td className={`py-2.5 font-mono text-[12px] ${HEALTH_TONE[s.health] ?? ""}`}>
                          {s.health}
                        </td>
                        <td className="py-2.5 tabular-nums text-slate-300">
                          {(s.success_rate * 100).toFixed(0)}%
                        </td>
                        <td className="py-2.5 tabular-nums text-slate-400">{s.total_runs}</td>
                        <td className="py-2.5 tabular-nums text-slate-500">
                          {s.avg_latency_ms ? `${Math.round(s.avg_latency_ms)}ms` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <Card>
          <Eyebrow>آخر عمليات الجمع</Eyebrow>
          {(!dash || dash.recent_runs.length === 0) && (
            <p className="text-sm text-slate-500">لا توجد عمليات بعد.</p>
          )}
          <ul className="space-y-1.5">
            {dash?.recent_runs.map((r) => (
              <li key={r.id} className="flex items-center justify-between border-b border-line/40 pb-1.5 text-[12.5px]">
                <span className="flex items-center gap-2">
                  <span className={`h-1.5 w-1.5 rounded-full ${r.status === "success" ? "bg-ok" : "bg-crit"}`} />
                  <span className="font-mono text-slate-400">
                    +{r.items_new} جديد · {r.items_versioned} نسخة · {r.items_duplicate} مكرر
                  </span>
                </span>
                <Badge tone="muted">{r.status}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <p className="mt-6 text-center text-[12px] leading-relaxed text-slate-500">
        كل الأرقام حقيقية من محرك الجمع. لا تُعرض بيانات وهمية. المصادر تُجمَع من الإنترنت العام
        عند نشرها على بنية بها وصول خارجي.
      </p>
    </div>
  );
}
