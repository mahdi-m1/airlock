#!/usr/bin/env python3
"""إصدار الوثيقة النهائية بصيغة Word.

Exports an approved draft as .docx — the form courts and clients actually
accept. Markdown is the office's working format; nobody files a .md.

البوابة تُشغَّل من هنا ولا تُتخطى: التصدير هو آخر خطوة قبل خروج الوثيقة من
المكتب، فلو أمكن تصدير مسودة لم تُجَز لصار كل ما قبله زينة. مسودة مردودة أو
معلّقة على تحكيم لا يُنتج لها ملف Word أصلًا.

    export_cli.py مسودة.md --kind memo --out cases/118/مذكرة.docx
    export_cli.py مسودة.md --kind pleading --out صحيفة.docx --no-gate  # للمعاينة
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

from lib.citation import render_clean  # noqa: E402
from lib.docx_writer import Style, write_docx  # noqa: E402

sys.path.insert(0, str(ROOT / "tools" / "citation-gate"))

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"

KIND_LABEL = {"memo": "مذكرة قانونية", "pleading": "مرافعة", "opinion": "رأي قانوني"}


def office_config() -> dict:
    p = ROOT / "config/office.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def run_gate(src: Path, kind: str, db: str) -> tuple[bool, str]:
    """تشغيل بوابة الإسناد. يعيد (أُجيزت، السبب)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gate", ROOT / "tools/citation-gate/gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    try:
        rep = gate.check(src, kind, db, office_config())
    except FileNotFoundError as exc:
        return False, str(exc)
    if not rep["passed"]:
        return False, ("رُدّت المسودة من بوابة الإسناد:\n    "
                       + "\n    ".join(rep["problems"][:6]))
    if rep["needs_adjudication"]:
        return False, (f"{len(rep['adjudicate'])} إسناد ينتظر التحكيم الدلالي — "
                       f"لا تُصدَّر وثيقة قبل حسمه")
    return True, f"{rep['citations_resolved']} إسناد مُحل ومسنود"


def main() -> int:
    ap = argparse.ArgumentParser(description="إصدار الوثيقة النهائية بصيغة Word")
    ap.add_argument("file", type=Path, help="المسودة بصيغة Markdown")
    ap.add_argument("--out", type=Path, required=True, help="ملف .docx الناتج")
    ap.add_argument("--kind", choices=["memo", "pleading", "opinion"], default="memo")
    ap.add_argument("--title", help="عنوان الوثيقة (افتراضيًا من نوعها)")
    ap.add_argument("--db", default=str(ROOT / "corpus/index/corpus.db"))
    ap.add_argument("--no-gate", action="store_true",
                    help="تخطّي بوابة الإسناد — للمعاينة فقط، لا للتسليم")
    ap.add_argument("--font", default=None, help="اسم الخط العربي")
    ap.add_argument("--size", type=float, default=None, help="حجم الخط بالنقاط")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"{C_R}الملف غير موجود: {args.file}{C_0}", file=sys.stderr)
        return 2
    if args.out.suffix.lower() != ".docx":
        print(f"{C_R}المخرج يجب أن ينتهي بـ.docx{C_0}", file=sys.stderr)
        return 2

    cfg = office_config()
    print(f"\n══ إصدار وثيقة Word ══")
    print(f"{C_D}المصدر: {args.file.name}   النوع: {KIND_LABEL[args.kind]}{C_0}\n")

    # ── بوابة الإسناد أولًا ──
    if args.no_gate:
        print(f"  {C_Y}!{C_0} تُخطّيت بوابة الإسناد — هذه معاينة لا وثيقة تسليم.")
    else:
        ok, why = run_gate(args.file, args.kind, args.db)
        if not ok:
            print(f"  {C_R}✗ لم تُصدَّر.{C_0} {why}\n")
            print(f"{C_D}  التصدير آخر خطوة قبل خروج الوثيقة، فلا يتخطى البوابة.\n"
                  f"  عالج الملاحظات ثم أعد المحاولة.{C_0}\n")
            return 1
        print(f"  {C_G}✓{C_0} اجتازت بوابة الإسناد — {why}")

    # ── تنظيف العلامات الآلية ──
    body = render_clean(args.file.read_text(encoding="utf-8"))
    if "⟦" in body:
        print(f"  {C_Y}!{C_0} بقيت علامات آلية بعد التنظيف — راجع الوثيقة")
    print(f"  {C_G}✓{C_0} أُزيلت علامات الإسناد الآلية")

    # ── ترويسة المسودة ──
    out_cfg = cfg.get("output", {})
    notice = None
    if out_cfg.get("draft_watermark"):
        notice = (out_cfg.get("draft_notice") or "").strip() or \
            "مسودة — تتطلب اعتماد محامٍ مقيّد قبل الإيداع."
        print(f"  {C_G}✓{C_0} أُضيفت ترويسة المسودة")
    else:
        print(f"  {C_Y}!{C_0} وسم المسودة مُطفأ في config/office.yaml — "
              f"تصدر بلا تمييز نظامي")

    st = Style()
    if args.font:
        st.font_cs = args.font
    if args.size:
        st.size_pt = args.size

    out = write_docx(body, args.out,
                     title=args.title or KIND_LABEL[args.kind],
                     draft_notice=notice, style=st)
    size = out.stat().st_size

    print(f"\n{C_G}✓ صدرت الوثيقة{C_0}  {out}  ({size:,} بايت)")
    print(f"{C_D}  عربية باتجاه من اليمين، خط {st.font_cs} بحجم {st.size_pt:g}، A4.\n"
          f"  محلية بالكامل — لم تغادر الجهاز.{C_0}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
