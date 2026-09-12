import { useCallback, useEffect, useState } from "react";
import { fetchReadiness, type Readiness } from "../lib/api";
import { Card, Eyebrow, StatusDot } from "./ui";

const SERVICE_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
  minio: "MinIO",
  opensearch: "OpenSearch",
  neo4j: "Neo4j",
};

// Reflects the API's real /health/ready probes. If a service is down, it shows
// here as down with the real error — nothing is faked green.
export function ServiceHealth() {
  const [data, setData] = useState<Readiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchReadiness());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 10000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <Card>
      <div className="flex items-center justify-between">
        <Eyebrow>صحّة الخدمات · /health/ready</Eyebrow>
        <button
          onClick={() => void load()}
          className="font-mono text-[11px] text-steel-soft hover:text-brass-soft"
        >
          تحديث
        </button>
      </div>

      {error && (
        <p className="font-mono text-sm text-crit">تعذّر الوصول إلى الـ API: {error}</p>
      )}

      <ul className="mt-2 divide-y divide-line/60">
        {Object.entries(SERVICE_LABELS).map(([key, label]) => {
          const svc = data?.services?.[key];
          const ok = loading && !data ? null : svc?.ok ?? false;
          return (
            <li key={key} className="flex items-center justify-between py-2.5">
              <span className="flex items-center gap-3">
                <StatusDot ok={ok} />
                <span className="text-sm text-slate-200">{label}</span>
              </span>
              <span className="font-mono text-[11px] text-slate-500">
                {ok === null
                  ? "..."
                  : svc?.ok
                    ? `${svc.latency_ms ?? "?"}ms`
                    : (svc?.error ?? "down")}
              </span>
            </li>
          );
        })}
      </ul>

      {data && (
        <p className="mt-3 font-mono text-[11px] text-slate-500">
          الحالة الكلية:{" "}
          <span className={data.status === "ready" ? "text-ok" : "text-warn"}>
            {data.status}
          </span>
        </p>
      )}
    </Card>
  );
}
