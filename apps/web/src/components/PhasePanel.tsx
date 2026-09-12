import { Card, Eyebrow, Badge } from "./ui";

// Honest capability map. P0 is the only implemented phase. Everything else is
// shown as NOT built yet — no clickable buttons that pretend to work, no fake
// map, no sample data. This panel exists so the UI never overstates the system.
interface Phase {
  id: string;
  title: string;
  status: "active" | "planned";
}

const PHASES: Phase[] = [
  { id: "P0", title: "الأساسات: الهوية، الصلاحيات، التدقيق، الصحّة", status: "active" },
  { id: "P1.1", title: "الجمع والأرشفة: RSS، الأرشيف، إزالة التكرار، الإصدارات", status: "active" },
  { id: "P1.2", title: "جامع الويب: استخراج المقالات، الفهرسة، same_event", status: "active" },
  { id: "P2", title: "المعالجة والإثراء", status: "planned" },
  { id: "P3", title: "GEOINT والخريطة", status: "planned" },
  { id: "P4", title: "الأحداث والخط الزمني", status: "planned" },
  { id: "P5", title: "الرسم المعرفي", status: "planned" },
  { id: "P6", title: "محرك البحث", status: "planned" },
  { id: "P7", title: "محرك التهديد والإنذار", status: "planned" },
  { id: "P8", title: "محرك التقارير", status: "planned" },
  { id: "P9", title: "المحلّل الآلي (RAG)", status: "planned" },
];

export function PhasePanel() {
  return (
    <Card>
      <Eyebrow>خريطة القدرات · ما هو مُنفَّذ فعلاً</Eyebrow>
      <ul className="space-y-1.5">
        {PHASES.map((p) => {
          const active = p.status === "active";
          return (
            <li
              key={p.id}
              className={`flex items-center justify-between rounded border px-3 py-2 ${
                active
                  ? "border-brass/40 bg-brass/5"
                  : "border-line/50 opacity-60"
              }`}
            >
              <span className="flex items-center gap-3">
                <span className="font-mono text-[11px] text-slate-400">{p.id}</span>
                <span className="text-[13px] text-slate-200">{p.title}</span>
              </span>
              {active ? (
                <Badge tone="brass">مُفعّل</Badge>
              ) : (
                <Badge tone="muted">غير مُنفّذ بعد</Badge>
              )}
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-[12px] leading-relaxed text-slate-500">
        المراحل غير المُفعّلة لا تملك واجهات عاملة في هذا الإصدار. لا تُعرض بيانات
        أمنية أو خريطة أو تقارير قبل تنفيذ مراحلها فعلياً.
      </p>
    </Card>
  );
}
