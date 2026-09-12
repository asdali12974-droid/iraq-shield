import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { searchArchive, searchArchiveFulltext, type ArchiveItem, type SearchArchiveFilters } from "../lib/api";
import { Card, Eyebrow, Badge } from "../components/ui";

export function Archive() {
  const { token } = useAuth();
  const [items, setItems] = useState<ArchiveItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isFulltextSearch, setIsFulltextSearch] = useState(false);
  const [isMetadataSearch, setIsMetadataSearch] = useState(false);
  const [metadataFilters, setMetadataFilters] = useState<SearchArchiveFilters>({});

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const result = await searchArchive(token);
      setItems(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  const handleFulltextSearch = useCallback(async () => {
    if (!token || !searchQuery.trim()) return;
    setLoading(true);
    setError(null);
    setIsFulltextSearch(true);
    setIsMetadataSearch(false);
    try {
      const result = await searchArchiveFulltext(token, searchQuery.trim(), 100);
      setItems(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, searchQuery]);

  const handleMetadataSearch = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    setIsFulltextSearch(false);
    setIsMetadataSearch(true);
    try {
      const result = await searchArchive(token, metadataFilters);
      setItems(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, metadataFilters]);

  const handleClear = useCallback(() => {
    setSearchQuery("");
    setMetadataFilters({});
    setIsFulltextSearch(false);
    setIsMetadataSearch(false);
    setError(null);
    void load();
  }, [load]);

  useEffect(() => {
    void load();

    // Only set up auto-refresh when NOT in search mode (fulltext or metadata).
    // During search, preserve results until user clicks Clear.
    if (!isFulltextSearch && !isMetadataSearch) {
      const id = setInterval(() => void load(), 10000);
      return () => clearInterval(id);
    }
  }, [load, isFulltextSearch, isMetadataSearch]);

  const formatDate = (dateStr: string): string => {
    try {
      const d = new Date(dateStr);
      return d.toISOString().slice(0, 19).replace("T", " ");
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-bold text-brass-soft">IRAQ SHIELD</span>
          <span className="text-slate-500">·</span>
          <span className="text-sm text-slate-400">الأرشيف</span>
        </div>
        <Link to="/" className="rounded border border-line px-3 py-1.5 text-[12px] text-slate-300 hover:border-brass">
          ← لوحة التشغيل
        </Link>
      </header>

      {error && <p className="mb-4 font-mono text-sm text-crit">تعذّر الوصول: {error}</p>}

      <Card>
        <div className="mb-6 space-y-3">
          <Eyebrow>بحث بواسطة البيانات الوصفية</Eyebrow>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">اللغة</label>
              <input
                type="text"
                value={metadataFilters.language || ""}
                onChange={(e) => setMetadataFilters({ ...metadataFilters, language: e.target.value || undefined })}
                placeholder="مثال: ar, en"
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">المؤلف</label>
              <input
                type="text"
                value={metadataFilters.author || ""}
                onChange={(e) => setMetadataFilters({ ...metadataFilters, author: e.target.value || undefined })}
                placeholder="اسم المؤلف"
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">نوع المحتوى</label>
              <input
                type="text"
                value={metadataFilters.content_type || ""}
                onChange={(e) => setMetadataFilters({ ...metadataFilters, content_type: e.target.value || undefined })}
                placeholder="مثال: application/json"
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">من (تاريخ)</label>
              <input
                type="date"
                value={metadataFilters.date_from || ""}
                onChange={(e) => setMetadataFilters({ ...metadataFilters, date_from: e.target.value || undefined })}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">إلى (تاريخ)</label>
              <input
                type="date"
                value={metadataFilters.date_to || ""}
                onChange={(e) => setMetadataFilters({ ...metadataFilters, date_to: e.target.value || undefined })}
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-400 mb-1">عدد النتائج (الحد: 500)</label>
              <input
                type="number"
                value={metadataFilters.limit || 100}
                onChange={(e) => setMetadataFilters({ ...metadataFilters, limit: parseInt(e.target.value) || undefined })}
                min="1"
                max="500"
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-brass focus:outline-none"
              />
            </div>
          </div>
          <div className="flex gap-2 pt-2">
            <button
              onClick={() => void handleMetadataSearch()}
              disabled={loading}
              className="rounded border border-brass px-3 py-2 text-sm font-medium text-brass hover:bg-brass/10 disabled:border-slate-600 disabled:text-slate-600 disabled:hover:bg-transparent"
            >
              بحث
            </button>
            <button
              onClick={handleClear}
              disabled={loading}
              className="rounded border border-line px-3 py-2 text-sm font-medium text-slate-400 hover:border-slate-300 hover:text-slate-300 disabled:opacity-50"
            >
              مسح الفلاتر
            </button>
          </div>
          {isMetadataSearch && (
            <p className="text-[12px] text-slate-500">
              نتائج البحث بالبيانات الوصفية —
              {metadataFilters.language && ` اللغة: ${metadataFilters.language} |`}
              {metadataFilters.author && ` المؤلف: ${metadataFilters.author} |`}
              {metadataFilters.content_type && ` النوع: ${metadataFilters.content_type}`}
            </p>
          )}
        </div>
      </Card>

      <Card>
        <div className="mb-6 space-y-3">
          <Eyebrow>بحث نصي كامل</Eyebrow>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyPress={(e) => {
                  if (e.key === "Enter") {
                    void handleFulltextSearch();
                  }
                }}
                placeholder="ابحث في الأرشيف…"
                className="w-full rounded border border-line bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-brass focus:outline-none"
                dir="rtl"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => void handleFulltextSearch()}
                disabled={loading || !searchQuery.trim()}
                className="rounded border border-brass px-3 py-2 text-sm font-medium text-brass hover:bg-brass/10 disabled:border-slate-600 disabled:text-slate-600 disabled:hover:bg-transparent"
              >
                بحث
              </button>
              <button
                onClick={handleClear}
                disabled={loading}
                className="rounded border border-line px-3 py-2 text-sm font-medium text-slate-400 hover:border-slate-300 hover:text-slate-300 disabled:opacity-50"
              >
                مسح
              </button>
            </div>
          </div>
          {isFulltextSearch && (
            <p className="text-[12px] text-slate-500">
              نتائج البحث عن: <span className="font-mono text-slate-400">"{searchQuery}"</span>
            </p>
          )}
        </div>
      </Card>

      <Card>
        <Eyebrow>
          عناصر الأرشيف {
            isFulltextSearch ? "- نتائج البحث النصي" : isMetadataSearch ? "- نتائج البحث بالبيانات الوصفية" : "الحالية"
          } ({items.length})
        </Eyebrow>

        {loading && !items.length && (
          <p className="text-sm text-slate-500">جارٍ التحميل…</p>
        )}

        {!loading && items.length === 0 && (
          <p className="text-sm text-slate-500">
            {isFulltextSearch ? "لا توجد نتائج للبحث النصي." : isMetadataSearch ? "لا توجد نتائج لهذه الفلاتر." : "لا توجد عناصر في الأرشيف."}
          </p>
        )}

        {items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-[12.5px]">
              <thead>
                <tr className="border-b border-line text-right font-mono text-[10.5px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 font-medium">العنوان</th>
                  <th className="py-2 font-medium">المؤلف</th>
                  <th className="py-2 font-medium">اللغة</th>
                  <th className="py-2 font-medium">المصدر</th>
                  <th className="py-2 font-medium">نُشِرَ</th>
                  <th className="py-2 font-medium">جُمِعَ</th>
                  <th className="py-2 font-medium">النسخة</th>
                  <th className="py-2 font-medium">الحالة</th>
                  <th className="py-2 font-medium">معرّف خارجي</th>
                  <th className="py-2 font-medium">الرابط</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b border-line/50">
                    <td className="py-2.5 text-slate-200">
                      {item.title || <span className="text-slate-500">—</span>}
                    </td>
                    <td className="py-2.5 text-slate-300">
                      {item.author || <span className="text-slate-500">—</span>}
                    </td>
                    <td className="py-2.5 text-slate-400">
                      {item.language || <span className="text-slate-500">—</span>}
                    </td>
                    <td className="py-2.5 font-mono text-[11.5px] text-slate-500">
                      {item.source_id.slice(0, 8)}…
                    </td>
                    <td className="py-2.5 font-mono text-[11px] text-slate-500">
                      {item.published_at ? formatDate(item.published_at) : "—"}
                    </td>
                    <td className="py-2.5 font-mono text-[11px] text-slate-400">
                      {formatDate(item.collected_at)}
                    </td>
                    <td className="py-2.5 text-center font-mono text-[11.5px] text-slate-400">
                      {item.version}
                    </td>
                    <td className="py-2.5 text-center">
                      <Badge tone={item.is_current ? "steel" : "muted"}>
                        {item.is_current ? "حالي" : "قديم"}
                      </Badge>
                    </td>
                    <td className="py-2.5 font-mono text-[11px] text-slate-500">
                      {item.external_id || <span className="text-slate-600">—</span>}
                    </td>
                    <td className="py-2.5">
                      {item.canonical_url ? (
                        <a
                          href={item.canonical_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-brass-soft hover:text-brass"
                        >
                          ↗
                        </a>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
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
