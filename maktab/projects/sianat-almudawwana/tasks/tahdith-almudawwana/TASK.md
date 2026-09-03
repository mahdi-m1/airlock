---
name: مراجعة المدونة القانونية وتحديثها
assignee: archivist
project: sianat-almudawwana
recurring: true
kind: task
---

راجع حالة المدونة وسُدّ نقصها:

1. `python3 tools/corpus/corpus_cli.py stats` — ما التشريعات غير المستوردة أو غير
   المتحقق منها؟
2. راجع القضايا الموسومة `نقص-مدونة` — أي تشريع أعجز قضية عن المضي؟
3. نزّل النصوص الرسمية الناقصة إلى `corpus/staging/<key>.html` من المصادر المدرجة
   في `corpus/sources.yaml` حصرًا.
4. `python3 tools/ingest/ingest.py --from-staging`
5. عالج تعارضات العناوين بتصحيح `sources.yaml` ليطابق النص الرسمي.
6. أعد معايرة عتبة التدقيق الدلالي — إلزامية بعد أي توسيع:
   `python3 scripts/calibrate-threshold.py --write`
   العتبة تُقاس من المدونة، فترتفع كلما كبرت. لا تمرر `--force` إن رفض السكربت.
7. أبلغ الشريك المدير: ما استُورد، وما بقي ناقصًا، وما يحتاج تنزيلًا يدويًا،
   والعتبة الجديدة إن تغيّرت.

تحقق أيضًا من عمر المدونة مقابل `citations.max_corpus_age_days` في
`config/office.yaml`، ونبّه إن تجاوزته.
