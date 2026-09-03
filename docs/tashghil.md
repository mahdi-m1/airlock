# تشغيل المكتب — الدليل الكامل

من مستودع مستنسخ إلى مذكرة بصيغة Word.

المكتب يعمل في **وضعين**، وأنت تختار بينهما:

| الوضع | ما يعمل | ما يحتاجه |
|---|---|---|
| **أ· الأدوات وحدها** | المدونة والبحث وبوابة الإسناد وفحص العقود ومعالجة المستندات وإصدار Word | بايثون فقط — بلا منصة ولا مفتاح نموذج |
| **ب· المكتب الكامل** | ما سبق، **زائد** الوكلاء الأحد عشر وخط القضايا الذي يفرض المراحل | Paperclip + مفتاح Anthropic + Linux مع `bwrap` |

ابدأ بالوضع (أ): يعمل خلال دقائق، ويبني المدونة التي لا يعمل الوضع (ب) بدونها
أصلًا. ثم انتقل إلى (ب).

> ⚠ **ما لم يُختبر:** المراحل 3–5 (تشغيل Paperclip والاستيراد والتهيئة) مكتوبة من
> فحص مصدر المنصة وحزمتها المنشورة، **ولم تُنفَّذ في بيئة البناء** — لا منفذ
> شبكي فيها لتشغيل خادم. كل ما عداها منفَّذ ومُختبر: 40 فحصًا في `e2e-test.sh`
> وسبع مجموعات اختبار. إن اختلف سلوك المنصة عمّا هنا، أبلغني بالمخرجات.

---

## 0· المتطلبات

```bash
git clone <رابط المستودع> airlock && cd airlock
./scripts/setup.sh
```

سكربت واحد: يفحص، ويعرض ما سيثبّته ويسألك، ويثبّته، ثم يعيد الفحص ويشغّل كل
الاختبارات (سلامة الحزمة، وسبع مجموعات، والاختبار الشامل).

| الخيار | متى |
|---|---|
| `--dry-run` | اعرض الأوامر ولا تنفّذ شيئًا |
| `--yes` | بلا أسئلة — للأتمتة |
| `--mode a` | متطلبات الأدوات وحدها، بلا Paperclip ولا عزل |
| `--no-sudo` | لا تلمس حزم النظام |
| `--with-node` | ثبّت Node 24 عبر nvm |
| `--tests-only` | الاختبارات فقط |

و`./scripts/install.sh` يفحص ويرشد بلا تثبيت، إن كنت تفضّل تنفيذ الأوامر بنفسك.

**ما يفحصه كلاهما:**

| المتطلب | لماذا | إن نقص |
|---|---|---|
| **Linux + `bwrap`** | عزل الشبكة يُفرض به. بدونه العزل وعدٌ نصي لا قيد تقني | `sudo apt install bubblewrap` |
| **Python ≥ 3.10 + PyYAML** | كل أدوات المكتب | `pip install pyyaml` |
| **sqlite3 مع FTS5** | البحث في المدونة | مضمّن في بايثون عادةً |
| **Node ≥ 24.11** | شرط Paperclip نفسه | للوضع (ب) فقط |
| **poppler-utils** | قراءة PDF — وأكثر المصادر الرسمية PDF | `sudo apt install poppler-utils` |
| **tesseract + ara** | المستندات الممسوحة والصور | `sudo apt install tesseract-ocr tesseract-ocr-ara` |
| **مفتاح Anthropic** | للوضع (ب) فقط | من لوحة تحكم حسابك |

`install.sh` يشغّل أيضًا فحص الحزمة وكل مجموعات الاختبار. **لا تتابع وقد بقي
`✗`.**

---

# الوضع (أ) — الأدوات وحدها

## 1· ابنِ المدونة القانونية

هذه أطول خطوة في المشروع كله، وكل ما بعدها يتوقف عليها: **بلا مدونة لا يصدر
المكتب إسنادًا واحدًا**، وبوابة الإسناد ترفض كل مسودة.

```bash
python3 scripts/build-corpus.py --plan      # ماذا سيفعل، دون أن يفعل
python3 scripts/build-corpus.py             # ينزّل ويحوّل ويستورد ويعايِر
```

السجل فيه **24 تشريعًا**، أرقامها وسنواتها **مرشّحات للتحقق لا حقائق**. تشريع
بلا رابط مسجَّل يظهر في قائمة «ما بقي عليك» مع أمر جاهز — السكربت لا يخترع رابطًا
ولا رقم جريدة.

للروابط الناقصة، استكشفها من المكتبة الإلكترونية لهيئة التشريع:

```bash
python3 scripts/build-corpus.py --discover               # رشّح واعرض السبب
python3 scripts/build-corpus.py --discover --write-urls  # سجّل القاطع (★) وحده
```

ثم سجّل توثيق الجريدة — وبدونه يبقى التشريع مستوردًا **غير قابل للاستشهاد**:

```bash
python3 tools/ingest/ingest.py --set-provenance civil-code \
    --url "https://www.lloc.gov.bh/…" --gazette <العدد> --date YYYY-MM-DD
python3 tools/ingest/ingest.py --urls        # ما وُثّق وما بقي
```

📘 التفصيل كاملًا — من أين تنزّل، وكيف تسمّي الملفات، وكل رسالة خطأ وعلاجها:
**[docs/bina-almudawwana.md](bina-almudawwana.md)**

**اعرف أين أنت في أي لحظة:**

```bash
python3 tools/corpus/corpus_cli.py stats     # ينتهي بسطر «الخطوة التالية»
```

**نصيحة:** ابدأ بتشريع واحد — قانون العمل — وتأكد أن مواده تظهر في البحث، ثم
كرّر. عشرون تشريعًا مستوردًا ومحققًا أنفع من أربعة وعشرين نصفها معلَّق.

## 2· ابحث في المدونة

```bash
python3 tools/corpus/corpus_cli.py search "الفصل التعسفي" --area labour
python3 tools/corpus/corpus_cli.py article law:36/2012 111
python3 tools/corpus/corpus_cli.py verify "⟦BH:law:36/2012:م111⟧"
```

البحث يعيد **مقاطع المواد فقط** لا القوانين كاملة — وهذا وحده الفرق بين دور بحث
بمئات التوكنز وآخر بعشرات الآلاف.

## 3· عالِج مستندات العميل

```bash
python3 tools/documents/extract_cli.py --backends          # ما المثبّت وما الناقص
python3 tools/documents/extract_cli.py عقد.pdf --out cases/118/mustanadat/aqd.md
```

**اقرأ رمز الخروج ولا تتجاهله:**

| الرمز | المعنى | ماذا تفعل |
|---|---|---|
| `0` | سليم | انقل منه |
| `3` | مقبول بتحفظ | **قابِل كل رقم وتاريخ واسم بالأصل** قبل النقل |
| `1` | غير صالح | لا تبنِ عليه واقعة |
| `2` | تعذّر | اتبع أمر التثبيت المعروض |

## 4· افحص مسودة قبل تسليمها

```bash
python3 tools/citation-gate/gate.py مسودة.md --kind memo \
    --render نهائية.md --worksheet tahkim.md
```

| رمز الخروج | المعنى |
|---|---|
| `0` | مقبولة — كُتبت الوثيقة النهائية بلا علامات آلية |
| `1` | مردودة — إسناد لا يُحل، أو مقدار مغلوط، أو قسم بلا سند |
| `3` | تحتاج تحكيمًا دلاليًا — اقرأ `tahkim.md` واحسم بندًا بندًا |
| `2` | عطب تشغيلي |

## 5· أصدِر بصيغة Word

```bash
python3 tools/documents/export_cli.py مسودة.md --kind memo --out cases/118/مذكرة.docx
```

**البوابة تُشغَّل من داخل الأداة ولا تُتخطى**: مسودة مردودة أو معلّقة على تحكيم
**لا يُنتج لها ملف Word أصلًا**.

## 6· افحص عقدًا

```bash
python3 tools/contracts/check_clauses.py --list            # الأنواع الستة وقوالبها
python3 tools/contracts/check_clauses.py عقد.md --type amal
```

بعد اكتمال المدونة، حوّل الفاحص من **منبّه** إلى **حاجز**:

```bash
python3 tools/contracts/fill_sanad.py                      # مرشّحات لكل بند
python3 tools/contracts/fill_sanad.py --apply corpus/index/sanad-review.md
python3 tools/contracts/fill_sanad.py --status
```

---

# الوضع (ب) — المكتب الكامل

## 7· حصّن البيئة

```bash
cp config/env.local.example config/env.local     # ينشئه install.sh تلقائيًا
# ضع ANTHROPIC_API_KEY داخله، ثم:
set -a; . ./config/env.local; set +a
./scripts/verify-isolation.sh
```

`env.local` يطفئ التليمتري ومشاركة التغذية الراجعة وفحص التحديثات، ويقصر الربط
على `127.0.0.1`. **متغيرات البيئة تتفوق على ملف إعداد Paperclip** — وهذا مقصود:
`onboard` يعيد كتابة `telemetry.enabled=true` في الملف.

> ⚠ الملف يحوي مفتاحك، وهو في `.gitignore`. لا ترفعه.

## 8· شغّل Paperclip

```bash
npx --registry https://registry.npmjs.org paperclipai onboard --yes
```

يشغّل الخادم على `http://localhost:3100` مع قاعدة PostgreSQL مضمّنة — بلا إعداد.

**أعد فحص التحصين بعده مباشرة:**

```bash
./scripts/verify-isolation.sh        # onboard يعيد تفعيل التليمتري في الملف
```

ثم استخرج رمز الوصول الذي تحتاجه أدوات التهيئة:

```bash
paperclipai auth login                                  # وصول لوحة التحكم
paperclipai token board create --name airlock --never-expires
export PAPERCLIP_API_URL=http://127.0.0.1:3100
export PAPERCLIP_API_KEY=<الرمز المطبوع>
```

## 9· استورد حزمة المكتب

```bash
npx paperclipai company import ./maktab --dry-run        # افحص أولًا
npx paperclipai company import ./maktab --target new \
    --new-company-name "مكتب الاستشارات القانونية" --yes
npx paperclipai company list                             # خذ معرّف الشركة
```

> المسار **موضعي** لا بـ`--from`، خلافًا لتوثيق Paperclip.

## 10· هيّئ الخط والعزل والسقوف

```bash
python3 scripts/provision.py --company-id <uuid> --dry-run   # عاين
python3 scripts/provision.py --company-id <uuid>
```

هذه الخطوة هي التي تجعل المكتب مكتبًا. تفعّل `enablePipelines` و`enableCases`،
وتنشئ خط `qadiya` بعشر مراحل وانتقالاته المسموحة مع `enforceTransitions`،
وتضبط المسارين الشبكيين، وتفرض السقوف اليومية والميزانيات.

**لماذا لا تُشحن في الحزمة:** `executionPolicy` حقل وقت تشغيل لكل شركة، وخوادم
MCP لا تُنقل في حزم الشركات. فما لا يُشحن يُهيَّأ بالسكربت.

## 11· شغّل أول قضية

في واجهة Paperclip على `http://localhost:3100`:

1. **افتح قضية جديدة** على خط `qadiya` — تبدأ من مرحلة «القيد والاستقبال».
2. **ألصق طلب العميل** وأرفق مستنداته.
3. **شغّل الأتمتة.** موظف القيد يعالج المرفقات ويملأ حقول المرحلة المهيكلة.
   الحقل غير المذكور يبقى فارغًا ويُدرج في «نقص المعلومات» — لا يُخمَّن.
4. **تسير القضية بنفسها:** فحص تعارض ← بحث ← تحليل ← صياغة ← تدقيق إسناد ←
   مراجعة قانونية ← تسليم. المرحلتان قبل التسليم **معتمِدهما وكيل لا بشر**،
   والرد يعيد المسودة إلى الصياغة تلقائيًا.
5. **المخرجات** تحت `cases/<رقم القضية>/` على جهازك، ولا تغادره.
6. **أصدِر النهائي** بأمر التصدير (المرحلة 5 أعلاه).

**ما لا يستطيع أي وكيل فعله:** تخطي مرحلة، أو تسليم مسودة لم تمر بتدقيق الإسناد
ثم المراجعة، أو الاستشهاد بتشريع غير مُتحقق، أو بلوغ أي موقع على الشبكة.

---

## 12· الصيانة الدورية

```bash
python3 scripts/build-corpus.py --refresh        # تحديث نصوص التشريعات
python3 tools/contracts/fill_sanad.py --status   # حالة أسناد بنود العقود
./scripts/verify-isolation.sh                    # بعد كل ترقية للمنصة
```

عمر المدونة المسموح قبل التنبيه: `citations.max_corpus_age_days` في
`config/office.yaml` (90 يومًا). وهذه دورة **أمين المصادر** ومهمته الدورية — لا
تحتاج إدارتها بنفسك بعد أول مرة.

## 13· القياس والتحقق

```bash
./scripts/e2e-test.sh                            # 40 فحصًا، بلا شبكة وبلا نموذج
python3 scripts/validate.py                      # سلامة الحزمة وتماسك الخط
./scripts/verify-isolation.sh                    # العزل والتحصين
python3 scripts/measure-tokens.py --company-id <uuid> --save baseline.json
```

---

## 14· حل المشكلات

| ما تراه | السبب | العلاج |
|---|---|---|
| `⚠ لا تشريع مُتحقق` | المدونة فارغة أو بلا توثيق | `build-corpus.py` ثم `--set-provenance` |
| `تعارض هوية: النص لا يعلن أنه law 37/2012` | رقم أو سنة خطأ في السجل، أو الملف لتشريع آخر | صحّح `sources.yaml` من صيغة الإصدار التي أعلنتها الرسالة |
| `تعارض عنوان: التطابق 30% < 60%` | العنوان المسجَّل لا يطابق النص | صحّح السجل ليطابق النص الرسمي، لا العكس |
| `لم يُعثر على أي مادة` | الملف صفحة فهرس أو صورة أو PDF لم يُحوَّل | تأكد أنه متن التشريع، وثبّت `poppler-utils` |
| `النطاق «…» خارج قائمة السماح` | رابط من مصدر غير مسجَّل | أضِف النطاق إلى `domains` إن كان رسميًا — وإلا فلا يدخل |
| `لا خلفية لقراءة PDF` | `poppler` غير مثبّت | `sudo apt install poppler-utils` |
| `رُفضت الكتابة — المدونة صغيرة` | معايرة تحت 150 مادة | وسّع المدونة، ولا تمرر `--force` |
| البوابة تعيد `3` دائمًا | العتبة غير مُعايَرة (تسقط إلى 0.35) | `calibrate-threshold.py --write` بعد اكتمال المدونة |
| `bwrap غير مثبّت` | لا عزل شبكي حقيقي | `sudo apt install bubblewrap` — **لا تشغّل الوضع (ب) بدونه** |
| `node … Paperclip يشترط 24.11` | نسخة Node قديمة | حدّثها قبل `onboard` |

---

## الخلاصة في عشرة أسطر

```bash
./scripts/install.sh                                   # 1. المتطلبات
python3 scripts/build-corpus.py --discover             # 2. رشّح روابط التشريعات
python3 tools/ingest/ingest.py --set-provenance …      # 3. سجّل التوثيق
python3 scripts/build-corpus.py                        # 4. ابنِ المدونة
python3 tools/corpus/corpus_cli.py stats               # 5. تأكد
set -a; . ./config/env.local; set +a                   # 6. حصّن (بعد وضع المفتاح)
./scripts/verify-isolation.sh
npx paperclipai onboard --yes                          # 7. شغّل المنصة
npx paperclipai company import ./maktab --target new --yes
python3 scripts/provision.py --company-id <uuid>       # 8. هيّئ الخط والعزل
```
