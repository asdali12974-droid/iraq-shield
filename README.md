# IRAQ SHIELD — درع العراق

منصة استخبارات مفتوحة المصدر (OSINT) تركّز على أمن العراق. هذا المستودع يحتوي
حالياً على **المرحلة P0 — الأساسات**: الهوية والصلاحيات (RBAC)، سجلّ التدقيق
(append-only)، فحوص الصحّة، الهجرات، وبنية تشغيل قابلة للتوسّع.

> **نطاق P0 صراحةً:** لا يوجد جمع بيانات، ولا معالجة، ولا خريطة، ولا محرك تهديد،
> ولا محلّل آلي بعد. هذه المكوّنات مجدولة للمراحل P1+. لا توجد **بيانات وهمية**
> في النظام، ولا واجهات تُظهر وظائف غير منفّذة على أنها تعمل.

---

## المكوّنات

| الخدمة | الدور | منفذ محلي |
|---|---|---|
| `api` (FastAPI) | الهوية، الصلاحيات، التدقيق، الصحّة | 8000 |
| `web` (React+TS) | تسجيل الدخول ولوحة التشغيل | 5173 |
| `postgres` (TimescaleDB-HA: PG16 + PostGIS + pgvector + TimescaleDB) | مصدر الحقيقة | 5432 |
| `redis` | طابور/تخزين مؤقت (أساس للمراحل القادمة) | 6379 |
| `minio` | تخزين الأرشيف الخام (أساس) | 9000 / 9001 |
| `opensearch` | فهرس البحث (أساس) | 9200 |
| `neo4j` | الرسم المعرفي (أساس) | 7474 / 7687 |

تفاصيل العلاقات بين المكوّنات في [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## التشغيل عبر Docker Compose (الطريقة الموصى بها)

المتطلبات: Docker + Docker Compose، ومنفذ وصول إلى Docker Hub لسحب الصور.

```bash
# 1) جهّز المتغيّرات
cp .env.example .env
# عدّل .env: اضبط كلمات المرور و IS_JWT_SECRET (استخدم: openssl rand -hex 32)
#           واضبط IS_BOOTSTRAP_ADMIN_EMAIL / IS_BOOTSTRAP_ADMIN_PASSWORD

# 2) شغّل كامل الحزمة
docker compose -f infra/docker-compose.yml --env-file .env up -d --build

# 3) تحقّق من الصحّة
curl -s http://localhost:8000/health          # liveness
curl -s http://localhost:8000/health/ready    # readiness (كل الخدمات)

# الواجهة:      http://localhost:5173
# توثيق الـAPI: http://localhost:8000/docs
```

عند أول إقلاع، حاوية `api` تنتظر جاهزية قواعد البيانات، ثم تُشغّل الهجرات
(`alembic upgrade head`)، ثم تزرع الأدوار والصلاحيات وتنشئ حساب المدير من
متغيّرات البيئة. العملية **idempotent** — تكرارها آمن.

### تسجيل الدخول
استخدم `IS_BOOTSTRAP_ADMIN_EMAIL` / `IS_BOOTSTRAP_ADMIN_PASSWORD` اللذين ضبطتهما.

---

## التشغيل للتطوير (بدون Docker)

يتطلب: Python 3.11+، Node 22+، وخدمات PostgreSQL و Redis عاملة محلياً
(الحدّ الأدنى للاختبار). MinIO/OpenSearch/Neo4j اختيارية للتطوير لكنها تظهر
"down" في `/health/ready` حتى تُشغَّل.

### الـ Backend
```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export IS_POSTGRES_HOST=127.0.0.1 IS_REDIS_HOST=127.0.0.1
export IS_JWT_SECRET=$(openssl rand -hex 32)
export IS_BOOTSTRAP_ADMIN_EMAIL=admin@iraqshield.local
export IS_BOOTSTRAP_ADMIN_PASSWORD='ضع-كلمة-مرور-قوية'

alembic upgrade head                 # الهجرات
python -m app.modules.iam.bootstrap  # زرع RBAC + المدير
uvicorn app.main:app --reload        # التشغيل على :8000
```

### الـ Frontend
```bash
cd apps/web
npm install
npm run dev        # على :5173 (يتصل بـ VITE_API_BASE_URL، الافتراضي :8000)
```

---

## الاختبارات

اختبارات التكامل تعمل على قواعد بيانات **حقيقية** (لا mocks). تحتاج PostgreSQL
و Redis عاملَين على الأقل؛ تُنشئ قاعدة `iraqshield_test` منفصلة تلقائياً.

```bash
cd apps/api && source .venv/bin/activate
export IS_POSTGRES_HOST=127.0.0.1 IS_REDIS_HOST=127.0.0.1
pytest -v

# للتحقق الكامل من readiness مع كل الخدمات (يتطلب حزمة docker كاملة):
IS_TEST_FULL_STACK=1 pytest -v
```

يغطّي: تجزئة كلمات المرور و JWT، تدفّق المصادقة، فرض RBAC، تسجيل التدقيق،
ضمان append-only على مستوى قاعدة البيانات، وفحوص الصحّة الحقيقية.

الفحص الساكن: `ruff check .`

---

## مسار الـ API (P0)

| الطريقة | المسار | الصلاحية |
|---|---|---|
| GET | `/health` | عام (liveness) |
| GET | `/health/ready` | عام (readiness) |
| POST | `/api/v1/auth/login` | عام |
| POST | `/api/v1/auth/refresh` | عام (توكن تحديث — يُدوَّر ويُبطَل القديم) |
| POST | `/api/v1/auth/logout` | عام (يُبطِل توكن التحديث) |
| GET | `/api/v1/auth/me` | مصادَق |
| GET | `/api/v1/admin/users` | `admin:users:read` |
| POST | `/api/v1/admin/users` | `admin:users:manage` |
| GET | `/api/v1/admin/roles` | `admin:roles:read` |
| GET | `/api/v1/audit` | `audit:read` |

الأدوار المزروعة: `viewer`, `analyst`, `senior_analyst`, `collector_manager`, `admin`.

---

## جمع قنوات Telegram العامة (P1.3)

يجمع **درع العراق** المنشورات من **قنوات Telegram العامة** التي يحدّدها المدير
عبر **الصفحة العامة** التي يوفّرها Telegram على `https://t.me/s/<username>` —
معاينة ويب رسمية لا تتطلّب أيّ مصادقة أو API أو حساب مستخدم.

المنصّة **لا تستخدم**: Telegram API / MTProto / Telethon / api_id / api_hash /
session_string / حساب مستخدم أو بوت / خدمات كشط أو وسطاء خارجيين.

**التفاصيل الكاملة:** [`docs/TELEGRAM.md`](docs/TELEGRAM.md).

| الطريقة | المسار | الصلاحية |
|---|---|---|
| POST | `/api/v1/sources` (`source_type=TELEGRAM_PUBLIC_WEB`) | `sources:manage` |
| POST | `/api/v1/sources/{id}/verify` | `sources:manage` |
| POST | `/api/v1/sources/{id}/collect` | `collection:run` |
| GET | `/api/v1/archive/{id}/relations` | `archive:read` |

القنوات تُزرَع معطّلة/`pending`؛ التصنيف التحريري (`OFFICIAL`/`POLITICAL_MEDIA`/
`MEDIA_OTHER`) يحدّده المدير، والموثوقية (A–F) منفصلة ويعدّلها المحلّل. الأرشيف
إلحاقيّ ومحميّ من الحذف؛ المحتوى المُعاد توجيهه يُربَط بمصدره الأصلي عبر
`forwarded_from`. زرع القائمة الأوّلية: `python -m scripts.seed_telegram_sources`.

**قيود صريحة:** صفحة `t.me/s/` تعرض نافذة محدودة من المنشورات الأخيرة فقط — لا
ندّعي الحصول على التاريخ الكامل للقناة. كود MTProto/Telethon مُبقى كـ adapter
مستقبلي فقط ولا يُستخدَم في مسار التشغيل الحالي.

---

## ملاحظات أمنية
- كلمات المرور مُجزّأة بـ **Argon2id** مع **سياسة كلمة مرور** (≥12 حرفاً، ≥3 أصناف).
- توكنات JWT (وصول قصير + تحديث)؛ توكنات التحديث **مخزّنة وقابلة للإبطال** مع
  **تدوير** واكتشاف **إعادة الاستخدام** (سرقة) و`/auth/logout`.
- **حماية Brute-force** لتسجيل الدخول عبر Redis (خنق لكل بريد/IP، ثم `429`).
- **رؤوس أمان** على كل استجابة (CSP، X-Frame-Options، nosniff…). أخطاء التحقق
  لا تُرجع المدخلات (لا تسريب لكلمة المرور).
- سجلّ التدقيق **غير قابل للتعديل** (trigger على مستوى قاعدة البيانات)؛ يسجّل
  الدخول/الخروج/الفشل/رفض الصلاحية/أفعال الإدارة، دون أي أسرار.
- الـ API يرفض الإقلاع في `IS_ENVIRONMENT=production` عند وجود أسرار افتراضية/ضعيفة
  (JWT، كلمات مرور DB/MinIO/Neo4j، `CORS=*`، `DEBUG=true`).
- في compose: كل المنافذ مربوطة بـ `127.0.0.1`، و**Redis يتطلّب كلمة مرور**
  (`IS_REDIS_PASSWORD`)، وحاوية الـ API تعمل بمستخدم غير جذر.
- المصادقة أصلية في P0؛ دمج Keycloak/OIDC مؤجَّل — انظر
  [`docs/adr/0001-native-auth-for-p0.md`](docs/adr/0001-native-auth-for-p0.md).
- **تقرير الوضع الأمني الكامل (PASS/WARNING):** [`docs/SECURITY.md`](docs/SECURITY.md).
