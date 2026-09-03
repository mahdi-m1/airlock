#!/usr/bin/env python3
"""تدقيق الحقول الحرجة في مستند مستخرَج — الطبقة الاحتياطية للقراءة الآلية.

    verify_fields.py عقد.pdf
    verify_fields.py مسح.jpg --out cases/12/tadqiq-hoqool.md
    verify_fields.py مسح.jpg --confirm cases/12/tadqiq-hoqool.md

لماذا هذه الأداة موجودة: التعرّف الضوئي **لا يُضمن**، وقراءة PDF العربي كذلك.
ودرجة الثقة في `extract_cli` تقيس شكل النص لا صحته: «٣٠ يومًا» تُقرأ «٣٧ يومًا»
فيبقى النص فصيحًا والثقة عالية والمدة خطأ.

ولا يعالج ذلك مراجعٌ آليّ يقرأ **النص**: الخانة الخاطئة اختفت من النص، ونموذج
يُطلب منه «التحقق» يجعله أفصح لا أصدق. فالطبقة هنا ثلاث:

  ١· قراءتان مستقلتان للملف نفسه بإعدادات مختلفة، والاختلاف بينهما إشارة.
  ٢· تماسك داخلي: تاريخ غير ممكن، مجموع لا يساوي مفرداته، مدة تناقض حدّيها،
     رقم شخصي تاريخه مستحيل، رقم بخانتين من كتابتين.
  ٣· تأكيد بشري للحقول الحرجة وحدها — لا للوثيقة كلها.

رموز الخروج:
    0  لا ملاحظة — الحقول متفقة ومتماسكة
    1  الحقول مؤكَّدة (مع --confirm) أو مرفوضة
    3  تحتاج مقابلة بالأصل — أُنتجت ورقة التدقيق
    2  خطأ تشغيلي
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from lib import fields as F  # noqa: E402
from lib.documents import DocumentError, detect_format, extract, passes  # noqa: E402

C_R, C_G, C_Y, C_B, C_D, C_0 = ("\033[31m", "\033[32m", "\033[33m", "\033[1m",
                                "\033[2m", "\033[0m")
CONFIRM_RE = re.compile(r"^\s*-\s*\*\*المقروء:\*\*\s*`(?P<val>[^`]*)`.*?"
                        r"^\s*-\s*\*\*بالأصل:\*\*\s*(?P<got>.*)$",
                        re.MULTILINE | re.DOTALL)


def worksheet(path: Path, items: list[F.Field], notes: list[str],
              diffs: list[str], fmt: str, methods: list[str]) -> str:
    out = [f"# تدقيق الحقول الحرجة — {path.name}",
           "",
           "القراءة الآلية **لا تُضمن**، وأخطر خطئها ما يبقى بعده النص سليمًا:",
           "رقم يتغيّر فتتغيّر معه مدة أو مبلغ، ولا يظهر ذلك في النص إطلاقًا.",
           "",
           "لكل حقل أدناه اكتب في سطر **بالأصل** ما تقرؤه في المستند نفسه:",
           "",
           "- القيمة كما هي إن طابقت.",
           "- القيمة الصحيحة إن اختلفت — وهي التي تدخل ملف القضية.",
           "- `غير مقروء` إن تعذّر — فلا يُبنى عليه شيء.",
           "",
           "لا تترك حقلًا فارغًا: الفراغ يعني «لم يُقابَل»، والأداة ترفضه.",
           "",
           f"**الملف:** `{path}`  ",
           f"**الصيغة:** {fmt}  ",
           f"**القراءات:** {'، '.join(methods)}  ",
           f"**حقول للمقابلة:** {len(items)}",
           ""]
    if diffs:
        out += ["## اختلاف بين القراءات — ابدأ من هنا", "",
                "قارئان اختلفا على هذه القيم. الاختلاف موضع الخطأ غالبًا:", ""]
        out += [f"- {d}" for d in diffs] + [""]
    if notes:
        out += ["## ملاحظات تماسك", "",
                "تُكتشف بلا الرجوع إلى الأصل — لكن حسمها يحتاجه:", ""]
        out += [f"- {n}" for n in notes] + [""]
    out += ["---", "", "## الحقول", ""]
    for n, f in enumerate(items, 1):
        out += [f"### {n}. {f.label} — سطر {f.line}", "",
                f"- **المقروء:** `{f.raw}`",
                f"- **مطبَّعًا:** `{f.value}`",
                f"- **السياق:** …{f.context}…",
                "- **بالأصل:** ", "", "---", ""]
    return "\n".join(out)


def read_confirmations(sheet: Path) -> tuple[int, list[str], list[str], list[str]]:
    """يعيد (المؤكَّدة، الفارغة، المصحَّحة، غير المقروءة).

    التصحيح أهم ما في الورقة: حقل كتب فيه المدقق غير ما قرأته الآلة هو خطأ
    قراءة وقع فعلًا — يُعلَن ليُعرف أن المستند لا يُقرأ آليًا بثقة، لا ليُبتلع.
    """
    text = sheet.read_text(encoding="utf-8")
    blocks = re.split(r"^### ", text, flags=re.MULTILINE)[1:]
    done, blank, fixed, unread = 0, [], [], []
    for b in blocks:
        title = b.split("\n", 1)[0].strip()
        m_read = re.search(r"\*\*المقروء:\*\*\s*`([^`]*)`", b)
        m_orig = re.search(r"\*\*بالأصل:\*\*[ \t]*(.*)", b)
        machine = (m_read.group(1).strip() if m_read else "")
        got = (m_orig.group(1).strip() if m_orig else "")
        if not got:
            blank.append(f"{title} — المقروء `{machine or '?'}`")
            continue
        done += 1
        if got in ("غير مقروء", "غير مقروءة", "غير واضح"):
            unread.append(f"{title} — المقروء آليًا `{machine}`")
        elif got.replace(" ", "") != machine.replace(" ", ""):
            fixed.append(f"{title}: الآلة `{machine}` ← بالأصل `{got}`")
    return done, blank, fixed, unread


def main() -> int:
    ap = argparse.ArgumentParser(
        description="تدقيق الحقول الحرجة في مستند مستخرَج",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("file")
    ap.add_argument("--out", type=Path, help="مسار ورقة التدقيق")
    ap.add_argument("--confirm", type=Path, metavar="SHEET",
                    help="افحص ورقة تدقيق مملوءة")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    src = Path(args.file)
    if not src.is_file():
        print(f"{C_R}ليس ملفًا: {src}{C_0}", file=sys.stderr)
        return 2

    if args.confirm:
        if not args.confirm.is_file():
            print(f"{C_R}ورقة التدقيق غير موجودة: {args.confirm}{C_0}", file=sys.stderr)
            return 2
        done, blank, fixed, unread = read_confirmations(args.confirm)
        print(f"\n{C_B}══ تأكيد الحقول — {args.confirm.name} ══{C_0}\n")
        if blank:
            print(f"  {C_R}✗ {len(blank)} حقلًا بلا مقابلة:{C_0}")
            for b in blank[:12]:
                print(f"    · {b}")
            if len(blank) > 12:
                print(f"    … و{len(blank) - 12} غيرها")
            print(f"\n{C_D}  الفراغ ليس موافقة. اكتب ما تقرؤه بالأصل في كل حقل.{C_0}\n")
            return 1
        print(f"  {C_G}✓ {done} حقلًا مقابَلًا بالأصل.{C_0}")
        if fixed:
            print(f"\n  {C_Y}⚠ {len(fixed)} حقلًا صحّحه المدقق — القراءة الآلية "
                  f"أخطأت فيها:{C_0}")
            for f in fixed:
                print(f"    · {f}")
            print(f"{C_D}  مستند أخطأت فيه القراءة مرة تُخطئ فيه ثانية: عامِل بقية "
                  f"أرقامه\n  بالحذر نفسه، ولا تستخرج منه شيئًا بلا مقابلة.{C_0}")
        if unread:
            print(f"\n  {C_Y}⚠ {len(unread)} حقلًا غير مقروء بالأصل:{C_0}")
            for u in unread:
                print(f"    · {u}")
            print(f"{C_D}  لا يُبنى عليه شيء. اطلب نسخة أوضح من العميل.{C_0}")
        print(f"\n{C_D}  ما كُتب في «بالأصل» هو المعتمد — لا ما قرأته الآلة.{C_0}\n")
        return 0

    try:
        ex = extract(src)
        reads = passes(src)
    except DocumentError as exc:
        print(f"{C_R}✗ {exc}{C_0}", file=sys.stderr)
        return 2

    items = F.find(ex.text)
    notes = F.consistency(items, ex.text)
    diffs = F.compare(reads)
    fmt = detect_format(src)

    if args.json:
        import json
        print(json.dumps({
            "file": str(src), "format": fmt, "reads": list(reads),
            "confidence": ex.confidence,
            "fields": [{"kind": f.kind, "raw": f.raw, "value": f.value,
                        "line": f.line} for f in items],
            "consistency": notes, "disagreements": diffs,
        }, ensure_ascii=False, indent=2))
        return 0 if not (notes or diffs or fmt in ("pdf",) or items) else 3

    print(f"\n{C_B}══ تدقيق الحقول الحرجة — {src.name} ══{C_0}")
    print(f"{C_D}الصيغة: {fmt}   القراءات: {'، '.join(reads)}   "
          f"ثقة الاستخراج: {ex.confidence:.0%}{C_0}\n")

    if not items:
        print(f"  {C_D}لا تواريخ ولا مبالغ ولا مدد ولا أرقام في النص.{C_0}")
        print(f"  {C_G}✓ لا حقول حرجة تحتاج مقابلة.{C_0}\n")
        return 0

    kinds: dict[str, int] = {}
    for f in items:
        kinds[f.label] = kinds.get(f.label, 0) + 1
    print("  " + " · ".join(f"{v} {k}" for k, v in kinds.items()))

    if len(reads) < 2:
        print(f"  {C_D}قراءة واحدة — الصيغة تُقرأ بمحلل حتمي، فلا معنى "
              f"لمقابلة قراءتين.{C_0}")
    elif diffs:
        print(f"\n  {C_R}✗ {len(diffs)} اختلافًا بين القراءات:{C_0}")
        for d in diffs[:8]:
            print(f"    · {d}")
        if len(diffs) > 8:
            print(f"    … و{len(diffs) - 8} غيرها")
    else:
        print(f"  {C_G}✓ القراءتان متفقتان على كل حقل.{C_0} "
              f"{C_D}(اتفاقهما يحصر الشك ولا يرفعه){C_0}")

    if notes:
        print(f"\n  {C_Y}⚠ {len(notes)} ملاحظة تماسك:{C_0}")
        for n in notes:
            print(f"    · {n}")

    # المقابلة بالأصل ليست ضريبة على كل مستند: DOCX يُقرأ بمحلل حتمي فالنص هو
    # ما في الملف حرفًا بحرف، ولا خطأ قراءة ممكنًا أصلًا. تُطلب حيث القراءة
    # استنتاج — PDF وصورة — أو حيث ظهرت ملاحظة أو اختلاف.
    from lib.documents import IMAGE_FORMATS  # noqa: PLC0415
    risky = fmt == "pdf" or fmt in IMAGE_FORMATS
    if not (risky or notes or diffs or not ex.ok):
        print(f"\n  {C_G}✓ لا مقابلة لازمة.{C_0} {C_D}المصدر يُقرأ بمحلل حتمي "
              f"(لا تعرّف ضوئي ولا استنتاج تخطيط)،\n  والحقول متماسكة. النص هو "
              f"ما في الملف حرفًا بحرف.{C_0}\n")
        return 0

    out = args.out or src.with_suffix(".tadqiq.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(worksheet(src, items, notes, diffs, fmt, list(reads)),
                   encoding="utf-8")
    print(f"\n  ورقة التدقيق: {out}")
    print(f"{C_D}  اكتب في «بالأصل» ما تقرؤه في المستند نفسه لكل حقل، ثم:{C_0}")
    print(f"    python3 tools/documents/verify_fields.py '{src}' --confirm '{out}'")
    print(f"\n{C_Y}⏳ الحقول تحتاج مقابلة بالأصل قبل بناء وقائع عليها.{C_0}\n")
    return 3


if __name__ == "__main__":
    sys.exit(main())
