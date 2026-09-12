import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { fetchAudit, type AuditEntry } from "../lib/api";
import { ServiceHealth } from "../components/ServiceHealth";
import { PhasePanel } from "../components/PhasePanel";
import { Card, Eyebrow, Badge } from "../components/ui";

function AuditFeed({ token }: { token: string }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchAudit(token)
      .then((e) => alive && setEntries(e))
      .catch(() => alive && setDenied(true));
    return () => {
      alive = false;
    };
  }, [token]);

  if (denied) return null; // viewer without audit:read — simply not shown.

  return (
    <Card>
      <Eyebrow>سجلّ التدقيق · آخر الأحداث</Eyebrow>
      {!entries && <p className="text-sm text-slate-500">جارٍ التحميل...</p>}
      {entries && entries.length === 0 && (
        <p className="text-sm text-slate-500">لا توجد أحداث بعد.</p>
      )}
      <ul className="space-y-1.5">
        {entries?.slice(0, 8).map((e) => (
          <li
            key={e.id}
            className="flex items-center justify-between gap-3 border-b border-line/40 pb-1.5 text-[12.5px]"
          >
            <span className="flex items-center gap-2">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  e.outcome === "success" ? "bg-ok" : "bg-crit"
                }`}
              />
              <span className="font-mono text-slate-300">{e.action}</span>
            </span>
            <span className="font-mono text-[11px] text-slate-500" dir="ltr">
              {e.actor_email ?? "—"}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function Dashboard() {
  const { user, token, logout } = useAuth();
  if (!user || !token) return null;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
          <span className="text-slate-500">·</span>
          <span className="text-sm text-slate-400">لوحة التشغيل — P0</span>
        </div>
        <div className="flex items-center gap-4">
          <Link
            to="/sources"
            className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass hover:text-brass-soft"
          >
            المصادر
          </Link>
          <Link
            to="/events"
            className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass hover:text-brass-soft"
          >
            الأحداث
          </Link>
          <span className="text-[13px] text-slate-300" dir="ltr">
            {user.email}
          </span>
          <button
            onClick={logout}
            className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-crit hover:text-crit"
          >
            خروج
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-1">
          <Card>
            <Eyebrow>المستخدم الحالي</Eyebrow>
            <p className="text-base text-slate-100">{user.full_name || user.email}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {user.role_names.map((r) => (
                <Badge key={r} tone="steel">
                  {r}
                </Badge>
              ))}
            </div>
            <div className="mt-4 space-y-1 font-mono text-[11px] text-slate-500">
              <div>مستوى التصريح: {user.clearance_level}</div>
              <div>عدد الصلاحيات: {user.permission_codes.length}</div>
            </div>
          </Card>
          <ServiceHealth />
        </div>

        <div className="space-y-5 lg:col-span-2">
          <PhasePanel />
          <AuditFeed token={token} />
        </div>
      </div>

      <footer className="mt-10 border-t border-line pt-4 text-center font-mono text-[11px] text-slate-600">
        IRAQ SHIELD · P0 foundation · مصادر عامة مشروعة · On-Prem
      </footer>
    </div>
  );
}
