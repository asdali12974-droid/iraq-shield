import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  fetchArchive,
  fetchSource,
  fetchSourceRuns,
  verifySource,
  type ArchiveItem,
  type CollectionRun,
  type Source,
} from "../lib/api";
import { Card, Eyebrow, Badge } from "../components/ui";

const HEALTH_TONE: Record<string, string> = {
  healthy: "text-ok",
  degraded: "text-warn",
  failed: "text-crit",
  pending: "text-slate-400",
  disabled: "text-slate-500",
};

const VERIFY_TONE: Record<string, string> = {
  verified: "text-ok",
  pending: "text-warn",
  failed: "text-crit",
  unsupported: "text-slate-500",
};

const VERIFY_LABEL: Record<string, string> = {
  verified: "مُوثَّق",
  pending: "بانتظار التحقق",
  failed: "فشل التحقق",
  unsupported: "غير مدعوم",
};

const CLASS_LABEL: Record<string, string> = {
  OFFICIAL: "رسمي",
  POLITICAL_MEDIA: "سياسي / إعلامي",
  MEDIA_OTHER: "إعلام آخر",
};

function Metric({ label, value, tone = "" }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded border border-line/60 px-3 py-2">
      <div className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

export function SourceDetail() {
  const { id } = useParams();
  const { token } = useAuth();
  const [source, setSource] = useState<Source | null>(null);
  const [runs, setRuns] = useState<CollectionRun[]>([]);
  const [items, setItems] = useState<ArchiveItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  const load = useCallback(async () => {
    if (!token || !id) return;
    try {
      const [s, r, a] = await Promise.all([
        fetchSource(token, id),
        fetchSourceRuns(token, id),
        fetchArchive(token, id),
      ]);
      setSource(s);
      setRuns(r);
      setItems(a);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [token, id]);

  const handleVerify = useCallback(async () => {
    if (!token || !id) return;
    setVerifying(true);
    setVerifyMsg(null);
    try {
      const res = await verifySource(token, id);
      setVerifyMsg(
        res.status === "verified"
          ? `تم التحقق: ${res.title ?? res.username}${res.channel_id ? ` (#${res.channel_id})` : ""}${res.posts_visible != null ? ` — ${res.posts_visible} منشور مرئي` : ""}`
          : res.status === "pending"
            ? "لا يمكن التحقق الآن — اتصال/اعتماد Telegram غير مُهيّأ. لم يُدّعَ التحقق."
            : `فشل التحقق: ${res.reason ?? "خطأ غير معروف"}`,
      );
      await load();
    } catch (e) {
      setVerifyMsg((e as Error).message);
    } finally {
      setVerifying(false);
    }
  }, [token, id, load]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 10000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between gap-4 border-b border-line pb-5">
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
          <span className="text-slate-500">·</span>
          <span className="text-sm text-slate-400">تفاصيل المصدر</span>
        </div>
        <Link to="/sources" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
          ← المصادر
        </Link>
      </header>

      {error && <p className="mb-4 font-mono text-sm text-crit">تعذّر الوصول: {error}</p>}

      {source && (
        <>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="text-xl font-bold text-slate-100">{source.name}</h1>
                <p dir="ltr" className="mt-1 font-mono text-[12px] text-slate-500">{source.url}</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone="steel">{source.source_type}</Badge>
                <span className={`font-mono text-sm ${HEALTH_TONE[source.health] ?? ""}`}>{source.health}</span>
                <Badge tone={source.enabled ? "brass" : "muted"}>{source.enabled ? "مفعّل" : "معطّل"}</Badge>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <Metric label="عناصر حالية" value={items.length} tone="text-brass-soft" />
              <Metric label="نسبة النجاح" value={`${(source.success_rate * 100).toFixed(0)}%`} />
              <Metric label="جولات" value={source.total_runs} />
              <Metric label="نجاح" value={source.success_count} tone="text-ok" />
              <Metric label="فشل" value={source.failure_count} tone={source.failure_count ? "text-crit" : ""} />
              <Metric label="متوسط الزمن" value={source.avg_latency_ms ? `${Math.round(source.avg_latency_ms)}ms` : "—"} />
            </div>
            {source.last_error && (
              <div className="mt-3 rounded border border-crit/40 bg-crit/5 px-3 py-2 font-mono text-[12px] text-crit" dir="ltr">
                آخر خطأ: {source.last_error}
              </div>
            )}
          </Card>

          {(source.source_type === "TELEGRAM_PUBLIC" || source.source_type === "TELEGRAM_PUBLIC_WEB") && (
            <Card className="mt-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Eyebrow>قناة تيليغرام عامة</Eyebrow>
                <div className="flex items-center gap-2">
                  <span className={`font-mono text-[12px] ${VERIFY_TONE[source.verification_status ?? "pending"] ?? ""}`}>
                    {VERIFY_LABEL[source.verification_status ?? "pending"] ?? source.verification_status}
                  </span>
                  <button
                    onClick={() => void handleVerify()}
                    disabled={verifying}
                    className="rounded border border-line px-3 py-1 text-[12px] text-slate-300 hover:border-brass disabled:opacity-40"
                  >
                    {verifying ? "جارٍ التحقق…" : "تحقق من القناة"}
                  </button>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric label="Username" value={source.telegram_username ? `@${source.telegram_username}` : "—"} />
                <Metric label="Channel ID" value={source.telegram_channel_id ?? "—"} />
                <Metric label="التصنيف" value={source.source_class ? (CLASS_LABEL[source.source_class] ?? source.source_class) : "—"} />
                <Metric label="الموثوقية" value={source.reliability} />
              </div>
              {source.telegram_title && (
                <p className="mt-3 text-[13px] text-slate-300" dir="auto">
                  <span className="text-slate-500">عنوان القناة: </span>{source.telegram_title}
                </p>
              )}
              {verifyMsg && (
                <div className="mt-3 rounded border border-line/60 bg-black/20 px-3 py-2 text-[12.5px] text-slate-300" dir="auto">
                  {verifyMsg}
                </div>
              )}
              <p className="mt-3 font-mono text-[11px] leading-relaxed text-slate-500" dir="auto">
                التصنيف يحدده مدير المنصة، والموثوقية يضبطها المحلل — كلاهما منفصل عن التحقق الآلي. لا يبدأ الجمع
                قبل تحقق حقيقي من القناة وتفعيلها. الجمع عبر الصفحة العامة (t.me/s/) يعرض نافذة محدودة من المنشورات الأخيرة فقط.
              </p>
            </Card>
          )}

          <Card className="mt-5">
            <Eyebrow>الخط الزمني للجمع</Eyebrow>
            {runs.length === 0 && <p className="text-sm text-slate-500">لا عمليات بعد.</p>}
            <ul className="space-y-2">
              {runs.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line/40 pb-2 text-[12.5px]">
                  <span className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${r.status === "success" ? "bg-ok" : r.status === "cancelled" ? "bg-warn" : "bg-crit"}`} />
                    <span className="font-mono text-slate-400" dir="ltr">
                      {new Date(r.started_at).toISOString().slice(0, 19).replace("T", " ")}
                    </span>
                    <Badge tone="muted">{r.status}</Badge>
                  </span>
                  <span className="font-mono text-[11.5px] text-slate-500">
                    +{r.items_new} جديد · {r.items_versioned} نسخة · {r.items_duplicate} مكرر
                    {r.items_discovered ? ` · ${r.items_discovered} مكتشف` : ""}
                    {r.items_failed ? ` · ${r.items_failed} فشل` : ""}
                    {r.latency_ms != null ? ` · ${r.latency_ms}ms` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
