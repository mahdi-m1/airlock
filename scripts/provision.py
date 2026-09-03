#!/usr/bin/env python3
"""تهيئة المكتب بعد الاستيراد — ما لا تستطيع حزمة الشركة حمله.

Post-import provisioning. The company package cannot carry any of this:

  * خط المعالجة ومراحله وانتقالاته (Pipelines ليست جزءًا من agentcompanies/v1)
  * عزل الشبكة لكل وكيل (networkScope/networkAllowlist)
  * السقوف اليومية وإلغاء النبضات الفارغة (غير ظاهرة في الواجهة أصلًا)
  * إعادة تفعيل ما يعطّله المستورد (المؤقتات، الأتمتة الموقوفة)

يُشغَّل بعد `paperclipai company import ./maktab`. آمن للتكرار (idempotent).

    export PAPERCLIP_API_URL=http://127.0.0.1:3100
    export PAPERCLIP_API_KEY=<token>
    python3 scripts/provision.py --company-id <uuid>
    python3 scripts/provision.py --company-id <uuid> --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"

PIPELINE_KEY = "qadiya"
PIPELINE_NAME = "خط معالجة القضايا"


class Api:
    def __init__(self, base: str, key: str, dry: bool):
        self.base, self.key, self.dry = base.rstrip("/"), key, dry

    def __call__(self, method: str, path: str, body: dict | None = None,
                 *, mutating: bool = True):
        url = f"{self.base}/api{path}"
        if self.dry and mutating:
            print(f"    {C_D}[محاكاة] {method} {path}{C_0}")
            return {}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.key}",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            raise SystemExit(
                f"{C_R}✗ {method} {path} → {e.code}{C_0}\n  {detail}\n"
                f"  {C_D}تأكد من PAPERCLIP_API_URL و PAPERCLIP_API_KEY وأن الخادم يعمل.{C_0}")
        except urllib.error.URLError as e:
            # المحاكاة يجب أن تعمل بلا خادم: نعرض الخطة كاملة بقيم بديلة.
            if self.dry:
                print(f"    {C_D}[محاكاة] {method} {path} (الخادم غير متاح){C_0}")
                return {}
            raise SystemExit(f"{C_R}✗ تعذر الوصول إلى {url}: {e.reason}{C_0}")


def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def deep_merge(base: dict, over: dict) -> dict:
    out = deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def package_agent_names() -> dict[str, str]:
    """slug → الاسم المعلن في AGENTS.md (وهو ما يحمله سجل الوكيل بعد الاستيراد)."""
    out = {}
    for d in sorted((ROOT / "maktab/agents").iterdir()):
        md = d / "AGENTS.md"
        if md.is_file():
            fm = yaml.safe_load(md.read_text(encoding="utf-8").split("---")[1]) or {}
            out[d.name] = fm.get("name", d.name)
    return out


def build_stages(slug_to_id: dict[str, str], lane_allow: list[str]) -> list[dict]:
    """تحويل تعريفات المراحل: أسماء الوكلاء → معرّفاتهم، وتنظيف المفاتيح الداخلية."""
    stages = json.loads((ROOT / "pipelines/qadiya.stages.json").read_text(encoding="utf-8"))
    out = []
    for s in stages:
        s = deepcopy(s)
        cfg = s.get("config", {})

        if slug := cfg.pop("_assigneeAgentSlug", None):
            cfg.setdefault("automation", {})["assigneeAgentId"] = slug_to_id[slug]
        if slug := cfg.pop("_approverAgentSlug", None):
            cfg["approver"] = {"kind": "agent", "id": slug_to_id[slug]}
            cfg["requireApproval"] = True
        # التوجيه حسب نوع المخرج يُنفَّذ في تعليمات المرحلة، فالمحرّك لا يدعم
        # إسنادًا شرطيًا. نُبقي الخريطة كتوثيق داخل نص التعليمات.
        if bv := cfg.pop("_assigneeByVariable", None):
            names = {k: slug for k, slug in bv.get("map", {}).items()}
            extra = "  ".join(f"إن كان {bv['variable']}=«{k}» فالمسؤول {v}."
                              for k, v in names.items())
            cfg.setdefault("automation", {})
            cfg["automation"]["instructionsBody"] = (
                cfg["automation"].get("instructionsBody", "") + "\n\n" + extra).strip()

        s["config"] = cfg
        out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="تهيئة مكتب الاستشارات القانونية")
    ap.add_argument("--company-id", required=True)
    ap.add_argument("--api-url", default=os.environ.get("PAPERCLIP_API_URL", "http://127.0.0.1:3100"))
    ap.add_argument("--api-key", default=os.environ.get("PAPERCLIP_API_KEY", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.api_key and not args.dry_run:
        print(f"{C_R}PAPERCLIP_API_KEY غير معرّف.{C_0}", file=sys.stderr)
        return 2

    api = Api(args.api_url, args.api_key, args.dry_run)
    cid = args.company_id
    agents_cfg = load_yaml(ROOT / "config/agents.yaml")
    office = load_yaml(ROOT / "config/office.yaml")
    sources = load_yaml(ROOT / "corpus/sources.yaml")
    defaults = agents_cfg.get("defaults", {})
    overrides = agents_cfg.get("overrides", {})

    print(f"\n══ تهيئة المكتب ══")
    print(f"{C_D}الخادم: {args.api_url}   الشركة: {cid}"
          f"{'   [محاكاة]' if args.dry_run else ''}{C_0}\n")

    # ── 1. تفعيل الميزات التجريبية ────────────────────────────────────
    print("1. تفعيل القضايا وخطوط المعالجة")
    api("PATCH", "/instance/settings/experimental",
        {"enablePipelines": True, "enableCases": True})
    print(f"   {C_G}✓{C_0} enablePipelines + enableCases")

    # ── 2. مطابقة الوكلاء ─────────────────────────────────────────────
    print("\n2. مطابقة الوكلاء")
    live = api("GET", f"/companies/{cid}/agents", mutating=False) or []
    live = live.get("agents", live) if isinstance(live, dict) else live
    by_name = {a.get("name"): a.get("id") for a in live}
    slug_to_id: dict[str, str] = {}
    missing = []
    for slug, name in package_agent_names().items():
        if aid := by_name.get(name):
            slug_to_id[slug] = aid
        else:
            missing.append(f"{slug} («{name}»)")
    if missing and not args.dry_run:
        print(f"   {C_R}✗ وكلاء غير موجودين في الشركة: {', '.join(missing)}{C_0}")
        print(f"   {C_D}استورد الحزمة أولًا: paperclipai company import ./maktab{C_0}")
        return 1
    for slug in package_agent_names():
        slug_to_id.setdefault(slug, f"<{slug}>")   # للمحاكاة فقط
    print(f"   {C_G}✓{C_0} {len(slug_to_id)} وكيل")

    # ── 3. عزل الشبكة وضبط التشغيل ────────────────────────────────────
    print("\n3. عزل الشبكة وسقوف التشغيل")
    official = [d["host"] for d in sources.get("domains", [])]
    for slug, aid in slug_to_id.items():
        ov = overrides.get(slug, {})
        adapter = deep_merge(defaults.get("adapter", {}), ov.get("adapter", {}))
        runtime = deep_merge(defaults.get("runtime", {}), ov.get("runtime", {}))

        # مسار المصادر وحده يبلغ النطاقات الرسمية؛ بقية الوكلاء لا يبلغونها.
        if ov.get("network_lane") == "masadir":
            adapter["networkAllowlist"] = sorted(set(adapter.get("networkAllowlist", []))
                                                 | set(official))
        api("PATCH", f"/agents/{aid}", {
            "adapterConfig": adapter,
            "runtimeConfig": runtime,
            "replaceAdapterConfig": False,
        })
        lane = "المصادر" if ov.get("network_lane") == "masadir" else "القضايا"
        print(f"   {C_G}✓{C_0} {slug:<20} مسار {lane}: "
              f"{len(adapter['networkAllowlist'])} نطاق، "
              f"{runtime['heartbeat']['maxDailyRuns']} تشغيل/يوم")

    # ── 4. الميزانيات ─────────────────────────────────────────────────
    print("\n4. الميزانيات")
    budget = office.get("budget", {})
    if cents := budget.get("company_monthly_cents"):
        api("PATCH", f"/companies/{cid}/budgets", {"budgetMonthlyCents": cents})
        print(f"   {C_G}✓{C_0} سقف الشركة الشهري: {cents/100:.0f}$")

    # ── 5. خط المعالجة ────────────────────────────────────────────────
    print("\n5. خط معالجة القضايا")
    existing = api("GET", f"/companies/{cid}/pipelines", mutating=False) or []
    existing = existing.get("pipelines", existing) if isinstance(existing, dict) else existing
    pid = next((p["id"] for p in existing if p.get("key") == PIPELINE_KEY), None)

    stages = build_stages(slug_to_id, official)
    trans = json.loads((ROOT / "pipelines/qadiya.transitions.json").read_text(encoding="utf-8"))
    edges = [{k: v for k, v in t.items() if not k.startswith("_")}
             for t in trans["transitions"]]

    if pid:
        print(f"   {C_D}الخط موجود ({pid}) — تحديث المراحل والانتقالات{C_0}")
        for s in stages:
            api("POST", f"/pipelines/{pid}/stages", s)
    else:
        created = api("POST", f"/companies/{cid}/pipelines", {
            "key": PIPELINE_KEY, "name": PIPELINE_NAME,
            "description": "خط ثابت لمعالجة القضايا: قيد، تعارض، بحث، تحليل، صياغة، تدقيق إسناد، مراجعة، تسليم.",
            "enforceTransitions": True,
            "stages": stages,
        })
        pid = created.get("id", "<pipeline>")
        print(f"   {C_G}✓{C_0} أُنشئ الخط بـ{len(stages)} مرحلة")

    api("PUT", f"/pipelines/{pid}/transitions",
        {"transitions": edges, "enforceTransitions": True})
    print(f"   {C_G}✓{C_0} {len(edges)} انتقال مسموح، والفرض مفعّل")

    # ── الخلاصة ───────────────────────────────────────────────────────
    print(f"\n{C_D}{'─' * 58}{C_0}")
    print(f"{C_G}✓ المكتب جاهز.{C_0}")
    print(f"""
  الخط يفرض الترتيب: لا وكيل يستطيع تخطي مرحلة، ولا تسليم دون
  اجتياز تدقيق الإسناد ثم المراجعة القانونية.

  وكلاء القضايا يبلغون واجهة النموذج فقط. أمين المصادر وحده يبلغ
  النطاقات الرسمية ({len(official)} نطاق) ولا يرى بيانات قضايا.

  الخطوة التالية — ابنِ المدونة القانونية قبل أول قضية:
    python3 tools/corpus/corpus_cli.py stats
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
