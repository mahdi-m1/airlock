---
name: siyaghat-alaqud
description: صياغة العقود والاتفاقيات وفق قوالب جاهزة مع فحص البنود الإلزامية والباطلة. استخدمها عند إعداد أو مراجعة عقد.
---

# صياغة العقود

## العطب هنا غير عطب المذكرة
المذكرة تُهزم بإسناد ملفّق. العقد يُهزم بـ**بند ناقص** أو **بند باطل**:

- **الناقص** لا يُرى وقت التوقيع، ويظهر عند النزاع حين لا يجد الطرف ما يحتج به.
- **الباطل** أسوأ: يطمئن العميل إلى حماية لا وجود لها. شرط يُسقط حقًا قرّره
  القانون للعامل لا يصير صحيحًا لأن العامل وقّع عليه.

لذلك العقود تمر بفاحص بنود حتمي، لا ببوابة الإسناد وحدها.

## الأداة

```
python3 tools/contracts/check_clauses.py <العقد>.md --type <النوع>
python3 tools/contracts/check_clauses.py --list        # الأنواع والقوالب
```

رمز الخروج: `0` مكتمل · `1` ينقصه بند إلزامي أو فيه بند باطل · `3` تحفظات.

## القوالب

| النوع | القالب |
|---|---|
| عقد عمل | [references/qalib-aqd-amal.md](references/qalib-aqd-amal.md) |
| عقد إيجار | [references/qalib-aqd-ijar.md](references/qalib-aqd-ijar.md) |
| عقد بيع | [references/qalib-aqd-bay.md](references/qalib-aqd-bay.md) |
| عقد خدمات | [references/qalib-aqd-khadamat.md](references/qalib-aqd-khadamat.md) |
| اتفاقية عدم إفشاء | [references/qalib-adam-ifsha.md](references/qalib-adam-ifsha.md) |
| اتفاق تسوية | [references/qalib-taswiya.md](references/qalib-taswiya.md) |

قواعد عامة تحكم كل عقد: [references/qawaid-alsiyagha.md](references/qawaid-alsiyagha.md)
والبنود التي تقع باطلة: [references/bunud-batila.md](references/bunud-batila.md)

## الإسناد في العقود
العقد لا يُثقل بالنصوص كالمذكرة، لكن **كل بند يقيّد حقًا أو يرتب جزاءً يحتاج
سندًا**. والقيود التي يرصدها الفاحص مبنية على `config/clauses.yaml`، وكل قيد
فيه يحمل علامة إسناد تُحل إلى المدونة — فما لم يُسند لا يُفرض.

## ممنوع
- نسخ قالب دون ملء كل حقل `<…>`. حقل غير مملوء في عقد موقّع فراغ يملؤه الخصم.
- بند يُسقط حقًا آمرًا. راجع `bunud-batila.md` قبل التسليم.
- إحالة غامضة («وفق الأنظمة المعمول بها») بديلًا عن بند صريح.
