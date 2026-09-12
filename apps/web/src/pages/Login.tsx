import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiException } from "../lib/api";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiException) {
        setError("بيانات الدخول غير صحيحة");
      } else {
        setError("تعذّر الاتصال بالخادم");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <svg viewBox="0 0 60 70" className="h-16 w-14" fill="none" aria-hidden>
            <path
              d="M30 2 L56 12 V34 C56 52 44 63 30 68 C16 63 4 52 4 34 V12 Z"
              fill="#1a1408"
              stroke="#C89A4C"
              strokeWidth="2.2"
            />
            <path
              d="M30 20 v26 M20 33 h20"
              stroke="#C89A4C"
              strokeWidth="2"
              strokeLinecap="round"
            />
            <circle cx="30" cy="33" r="4.4" fill="#0b1118" stroke="#C89A4C" strokeWidth="2" />
          </svg>
          <h1 className="mt-4 font-mono text-lg font-bold tracking-wide text-brass-soft">
            IRAQ SHIELD
          </h1>
          <p className="text-sm text-slate-400">درع العراق — منصة الاستخبارات المفتوحة</p>
        </div>

        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-md border border-line bg-surface/70 p-6"
        >
          <div>
            <label className="mb-1 block text-[13px] text-slate-300">البريد الإلكتروني</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              dir="ltr"
              className="w-full rounded border border-line bg-ink px-3 py-2 text-sm text-slate-100 outline-none focus:border-brass"
              placeholder="admin@iraqshield.local"
            />
          </div>
          <div>
            <label className="mb-1 block text-[13px] text-slate-300">كلمة المرور</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              dir="ltr"
              className="w-full rounded border border-line bg-ink px-3 py-2 text-sm text-slate-100 outline-none focus:border-brass"
            />
          </div>

          {error && <p className="text-[13px] text-crit">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded bg-brass px-4 py-2 text-sm font-semibold text-ink transition hover:bg-brass-soft disabled:opacity-50"
          >
            {busy ? "جارٍ التحقّق..." : "تسجيل الدخول"}
          </button>
        </form>
        <p className="mt-4 text-center font-mono text-[11px] text-slate-600">
          P0 · Authentication foundation
        </p>
      </div>
    </div>
  );
}
