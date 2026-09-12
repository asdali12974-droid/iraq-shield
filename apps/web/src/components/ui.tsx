import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-md border border-line bg-surface/70 p-5 shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="mb-3 font-mono text-[10.5px] uppercase tracking-[0.18em] text-steel-soft/70">
      {children}
    </div>
  );
}

export function StatusDot({ ok }: { ok: boolean | null }) {
  const color =
    ok === null ? "bg-warn animate-pulse" : ok ? "bg-ok" : "bg-crit";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "brass" | "steel" | "muted";
}) {
  const tones: Record<string, string> = {
    neutral: "border-line text-slate-300",
    brass: "border-brass/50 text-brass-soft",
    steel: "border-steel/50 text-steel-soft",
    muted: "border-line/60 text-slate-500",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[11px] ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
