#!/usr/bin/env python3
"""استخراج نص مستندات القضية — الأداة التي يستدعيها الوكلاء.

Extracts text from a client document and reports how far it can be trusted.

    extract_cli.py عقد.pdf
    extract_cli.py مسح.jpg --out cases/12/mustanadat/masah.md
    extract_cli.py --backends            # ما المثبّت وما الناقص

بوابة الجودة: الاستخراج ضعيف الثقة **لا يُمرَّر بصمت**. مستند ممسوح بلا طبقة
نصية يعطي نصًا فارغًا، وPDF عربي كثيرًا ما يعطي حروفًا مفصولة أو أشكال عرض —
وكلها تبدو نصًا وتصير «وقائع» إن لم تُرصد. رمز الخروج يميّز الحالات:

    0  مقبول
    1  مرفوض — استخراج غير صالح، لا تبنِ عليه واقعة
    3  مقبول بتحفظات — راجع المستند الأصلي قبل الاعتماد
    2  خطأ تشغيلي (ملف مفقود، أداة ناقصة)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from lib.documents import DocumentError, available_backends, extract  # noqa: E402

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"

INSTALL_HINTS = {
    "pdf": "sudo apt install poppler-utils   (أو: pip install pypdf)",
    "ocr": "sudo apt install tesseract-ocr tesseract-ocr-ara",
    "legacy_doc": "sudo apt install libreoffice  (للتحويل المعزول فقط)",
}
LABELS = {"pdf": "قراءة PDF", "ocr": "التعرّف الضوئي (صور ومسح)",
          "legacy_doc": "صيغ Office القديمة"}


def show_backends() -> int:
    have = available_backends()
    print("\n══ خلفيات معالجة المستندات ══\n")
    print(f"{C_D}هذه تعمل بالمكتبة القياسية بلا تثبيت: DOCX، ODT، RTF، HTML، نص{C_0}\n")
    missing = 0
    for key, label in LABELS.items():
        if have[key]:
            print(f"  {C_G}✓{C_0} {label:<28} {C_D}{have[key]}{C_0}")
        else:
            missing += 1
            print(f"  {C_R}✗{C_0} {label:<28} {C_D}{INSTALL_HINTS[key]}{C_0}")
    if missing:
        print(f"\n{C_Y}  {missing} خلفية ناقصة.{C_0} المستندات التي تحتاجها تُرفض "
              f"صراحةً\n  ولا تُعالَج بنص فارغ يُبنى عليه.\n")
    else:
        print(f"\n  {C_G}كل الخلفيات متاحة.{C_0}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="استخراج نص مستندات القضية بأمان")
    ap.add_argument("file", nargs="?", type=Path)
    ap.add_argument("--out", type=Path, help="كتابة النص المستخرج إلى ملف")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--backends", action="store_true", help="عرض الخلفيات المتاحة")
    ap.add_argument("--lang", default="ara+eng", help="لغات التعرّف الضوئي")
    ap.add_argument("--expect-latin", action="store_true",
                    help="المستند بغير العربية — لا تُنبّه على قلة الحروف العربية")
    args = ap.parse_args()

    if args.backends:
        return show_backends()
    if not args.file:
        ap.error("مطلوب مسار ملف، أو --backends")

    try:
        r = extract(args.file, expect_arabic=not args.expect_latin, ocr_lang=args.lang)
    except DocumentError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"\n{C_R}✗ تعذّر الاستخراج{C_0} — {args.file.name}\n")
            for line in str(exc).splitlines():
                print(f"  {line}")
            print(f"\n{C_D}  لا تبنِ أي واقعة على هذا المستند حتى يُقرأ.{C_0}\n")
        return 2

    strong = r.ok and not r.warnings

    if args.json:
        print(json.dumps({
            "ok": r.ok, "format": r.fmt, "method": r.method, "pages": r.pages,
            "confidence": r.confidence, "sha256": r.sha256, "bytes": r.bytes,
            "chars": len(r.text), "truncated": r.truncated,
            "warnings": r.warnings, "text": r.text,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n══ استخراج — {args.file.name} ══")
        print(f"{C_D}الصيغة: {r.fmt}   الطريقة: {r.method}"
              f"{f'   الصفحات: {r.pages}' if r.pages else ''}"
              f"   المحارف: {len(r.text)}{C_0}")
        print(f"{C_D}البصمة: {r.sha256[:16]}…{C_0}\n")
        col = C_G if strong else (C_Y if r.ok else C_R)
        print(f"  الثقة: {col}{r.confidence:.0%}{C_0}")
        for w in r.warnings:
            print(f"  {C_Y}!{C_0} {w}")
        print()
        if not r.ok:
            print(f"{C_R}✗ الاستخراج غير صالح للاعتماد.{C_0}")
            print(f"{C_D}  لا تبنِ عليه واقعة ولا تنقل منه رقمًا. اطلب نسخة أوضح من\n"
                  f"  العميل، أو مرّر المستند على التعرّف الضوئي إن كان ممسوحًا.{C_0}\n")
        elif r.warnings:
            print(f"{C_Y}⚠ مقبول بتحفظات.{C_0}")
            print(f"{C_D}  قابِل كل تاريخ ومبلغ واسم بالمستند الأصلي قبل نقله إلى\n"
                  f"  ملف القضية. التحريف هنا كالتحريف في الإسناد.{C_0}\n")
        else:
            print(f"{C_G}✓ استخراج سليم.{C_0}\n")
        if not args.out:
            print(f"{C_D}{'─' * 58}{C_0}")
            print(r.text[:2000] + ("\n…" if len(r.text) > 2000 else ""))
            print()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        header = (f"<!-- مستخرج آليًا من {args.file.name}\n"
                  f"     الصيغة: {r.fmt} · الطريقة: {r.method}\n"
                  f"     البصمة: {r.sha256}\n"
                  f"     الثقة: {r.confidence:.0%}"
                  + ("".join(f"\n     تحفظ: {w}" for w in r.warnings) if r.warnings else "")
                  + " -->\n\n")
        args.out.write_text(header + r.text, encoding="utf-8")
        if not args.json:
            print(f"{C_D}كُتب: {args.out}{C_0}\n")

    return 0 if strong else (3 if r.ok else 1)


if __name__ == "__main__":
    sys.exit(main())
