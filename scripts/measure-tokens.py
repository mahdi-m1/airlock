#!/usr/bin/env python3
"""قياس استهلاك التوكنز — أرقام فعلية لا تقديرات.

Token measurement. Reads what the platform actually recorded, so the
"we reduced tokens" claim is checkable rather than asserted.

مصدران:
  * `promptMetrics` — أحرف كل قسم من الموجّه لكل تشغيل، فيبيّن **أين** تذهب
    التوكنز (التعليمات؟ المهارات؟ سياق المهمة؟) لا كم فقط.
  * `/costs/by-agent-model` — الإنفاق الفعلي لكل وكيل ولكل نموذج.

    python3 scripts/measure-tokens.py --company-id <uuid>
    python3 scripts/measure-tokens.py --company-id <uuid> --baseline before.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"


def get(base: str, key: str, path: str):
    req = urllib.request.Request(f"{base.rstrip('/')}/api{path}",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"{C_R}✗ GET {path} → {e.code}: "
              f"{e.read().decode(errors='replace')[:200]}{C_0}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"{C_R}✗ تعذر الوصول: {e.reason}{C_0}", file=sys.stderr)
    return None


def rows_of(payload, *keys):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in keys:
            if isinstance(payload.get(k), list):
                return payload[k]
    return []


def fmt(n: float) -> str:
    return f"{n/1_000_000:.2f}M" if n >= 1_000_000 else (
        f"{n/1_000:.1f}k" if n >= 1_000 else f"{n:.0f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="قياس استهلاك التوكنز في المكتب")
    ap.add_argument("--company-id", required=True)
    ap.add_argument("--api-url", default=os.environ.get("PAPERCLIP_API_URL", "http://127.0.0.1:3100"))
    ap.add_argument("--api-key", default=os.environ.get("PAPERCLIP_API_KEY", ""))
    ap.add_argument("--save", type=Path, help="حفظ القياس كخط أساس للمقارنة لاحقًا")
    ap.add_argument("--baseline", type=Path, help="مقارنة بخط أساس محفوظ")
    args = ap.parse_args()

    if not args.api_key:
        print(f"{C_R}PAPERCLIP_API_KEY غير معرّف.{C_0}", file=sys.stderr)
        return 2

    data = get(args.api_url, args.api_key,
               f"/companies/{args.company_id}/costs/by-agent-model")
    if data is None:
        return 1
    rows = rows_of(data, "byAgentModel", "rows", "items", "data")

    print(f"\n══ قياس التوكنز ══")
    print(f"{C_D}{datetime.now(timezone.utc).isoformat(timespec='seconds')}{C_0}\n")

    if not rows:
        print(f"{C_Y}لا بيانات تكلفة بعد — شغّل قضية واحدة على الأقل ثم أعد القياس.{C_0}\n")
        return 0

    tot_in = tot_out = tot_cache = tot_cents = 0
    print(f"  {'الوكيل':<22}{'النموذج':<28}{'دخل':>9}{'مخبأ':>9}{'خرج':>9}{'التكلفة':>10}")
    print(f"  {C_D}{'─' * 87}{C_0}")
    for r in sorted(rows, key=lambda x: -(x.get("costCents") or 0)):
        ai = r.get("inputTokens") or 0
        ac = r.get("cachedInputTokens") or 0
        ao = r.get("outputTokens") or 0
        cc = r.get("costCents") or 0
        tot_in += ai; tot_out += ao; tot_cache += ac; tot_cents += cc
        name = str(r.get("agentName") or r.get("agentId") or "?")[:21]
        model = str(r.get("model") or "?")[:27]
        print(f"  {name:<22}{model:<28}{fmt(ai):>9}{fmt(ac):>9}{fmt(ao):>9}{cc/100:>9.2f}$")

    print(f"  {C_D}{'─' * 87}{C_0}")
    print(f"  {'الإجمالي':<50}{fmt(tot_in):>9}{fmt(tot_cache):>9}"
          f"{fmt(tot_out):>9}{tot_cents/100:>9.2f}$")

    if tot_in + tot_cache:
        hit = tot_cache / (tot_in + tot_cache) * 100
        print(f"\n  نسبة إصابة التخزين المؤقت: {hit:.0f}%")
        if hit < 30:
            print(f"  {C_Y}!{C_0} نسبة منخفضة. المنصة لا تنفّذ cache_control بنفسها —"
                  f" الإصابة تعتمد على ثبات بادئة الموجّه.\n"
                  f"    {C_D}راجع طول AGENTS.md والمهارات المركّبة: كل تغيّر في"
                  f" البادئة يبطل التخزين المؤقت للتشغيل التالي.{C_0}")

    snapshot = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "input": tot_in, "cached": tot_cache, "output": tot_out,
                "cents": tot_cents}

    if args.baseline and args.baseline.exists():
        base = json.loads(args.baseline.read_text(encoding="utf-8"))
        print(f"\n  {C_D}مقارنة بخط الأساس ({base['at']}){C_0}")
        for label, k in (("توكنز الدخل", "input"), ("توكنز الخرج", "output"),
                         ("التكلفة (سنت)", "cents")):
            b, n = base.get(k, 0), snapshot[k]
            if not b:
                continue
            d = (n - b) / b * 100
            col = C_G if d < 0 else (C_R if d > 5 else C_Y)
            print(f"    {label:<16}{fmt(b):>10} → {fmt(n):>10}   {col}{d:+.0f}%{C_0}")

    if args.save:
        args.save.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n  {C_D}حُفظ خط الأساس: {args.save}{C_0}")

    print(f"""
  {C_D}لمعرفة **أين** تذهب التوكنز داخل الموجّه، افحص promptMetrics في سجل
  أي تشغيل: instructionsChars (حجم AGENTS.md)، taskContextChars (سياق المهمة)،
  heartbeatPromptChars. أكبر مستهلك ثابت عادةً هو مهارة التشغيل المركّبة قسرًا.{C_0}
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
