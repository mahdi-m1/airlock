#!/usr/bin/env python3
"""تحقق من سلامة حزمة المكتب قبل الاستيراد.

Validates the office package before it reaches Paperclip. Catches the failures
that are silent or confusing at import time:

  * وصف متعدد الأسطر في frontmatter — محلل الاستيراد لا يدعم block scalars،
    فيتحول `description: >` إلى القيمة الحرفية ">" في COMPANY/AGENTS/PROJECT/TASK.
  * مرجع مهارة أو وكيل لا وجود له.
  * مفتاح متغير مرحلة بأحرف غير لاتينية — المحرّك يشترط ^[A-Za-z][A-Za-z0-9_]*$.
  * انتقال إلى مرحلة غير معرّفة، أو مخرج مراجعة لا يقابله انتقال مسموح.
  * دور (role) خارج القائمة التي تعرفها المنصة.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
C_R, C_G, C_Y, C_D, C_0 = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"

VALID_ROLES = {"ceo", "cto", "cmo", "cfo", "security", "engineer", "designer",
               "pm", "qa", "devops", "researcher", "general"}
VAR_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
STAGE_KINDS = {"working", "review", "done", "cancelled"}

errors: list[str] = []
warns: list[str] = []


def err(m): errors.append(m)
def warn(m): warns.append(m)


def frontmatter(path: Path) -> tuple[dict, str]:
    """يعيد (الحقول، المتن). يبلّغ عن block scalars لأن المستورد لا يفهمها."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        err(f"{path}: لا يبدأ بـfrontmatter")
        return {}, text
    _, fm, body = text.split("---", 2)
    rel = path.relative_to(ROOT)
    for line in fm.splitlines():
        if re.match(r"^(description|name|title|capabilities)\s*:\s*[>|][-+]?\s*$", line):
            key = line.split(":")[0].strip()
            err(f"{rel}: الحقل «{key}» يستخدم block scalar — محلل الاستيراد لا "
                f"يدعمها ويحوّل القيمة إلى «>». اجعلها سطرًا واحدًا.")
    try:
        return yaml.safe_load(fm) or {}, body
    except yaml.YAMLError as e:
        err(f"{rel}: frontmatter غير صالح: {e}")
        return {}, body


# ── 1. الشركة ─────────────────────────────────────────────────────────
pkg = ROOT / "maktab"
company_md = pkg / "COMPANY.md"
if not company_md.exists():
    err("maktab/COMPANY.md مفقود — الاستيراد يفشل بدونه")
    company = {}
else:
    company, _ = frontmatter(company_md)
    for k in ("name", "description", "slug"):
        if not company.get(k):
            err(f"COMPANY.md: الحقل «{k}» مطلوب")

# ── 2. الوكلاء ────────────────────────────────────────────────────────
agents: dict[str, dict] = {}
skills = {p.name for p in (pkg / "skills").iterdir() if p.is_dir()} \
    if (pkg / "skills").exists() else set()

for d in sorted((pkg / "agents").iterdir()) if (pkg / "agents").exists() else []:
    if not d.is_dir():
        continue
    md = d / "AGENTS.md"
    if not md.exists():
        err(f"agents/{d.name}: AGENTS.md مفقود")
        continue
    fm, _ = frontmatter(md)
    agents[d.name] = fm
    if (role := fm.get("role")) and role not in VALID_ROLES:
        err(f"agents/{d.name}: role «{role}» غير معروف للمنصة "
            f"(المسموح: {', '.join(sorted(VALID_ROLES))})")
    for s in fm.get("skills") or []:
        if s not in skills:
            err(f"agents/{d.name}: يشير إلى مهارة «{s}» غير موجودة في الحزمة")

ceos = [k for k, v in agents.items() if v.get("role") == "ceo"]
if len(ceos) != 1:
    err(f"يجب أن يكون في الشركة رئيس واحد بالضبط (role: ceo) — وُجد {len(ceos)}")

for name, fm in agents.items():
    mgr = fm.get("reportsTo")
    if mgr and mgr not in agents:
        err(f"agents/{name}: reportsTo «{mgr}» ليس وكيلًا في الحزمة")
    if mgr is None and name not in ceos:
        warn(f"agents/{name}: بلا reportsTo وليس رئيسًا — سيظهر خارج الهيكل")

# ── 3. المهارات ───────────────────────────────────────────────────────
for s in sorted(skills):
    md = pkg / "skills" / s / "SKILL.md"
    if not md.exists():
        err(f"skills/{s}: SKILL.md مفقود")
        continue
    fm, body = frontmatter(md)
    if fm.get("name") != s:
        err(f"skills/{s}: الحقل name=«{fm.get('name')}» لا يطابق اسم المجلد")
    if not SKILL_NAME_RE.match(str(fm.get("name", ""))):
        err(f"skills/{s}: الاسم يجب أن يطابق ^[a-z0-9]+(-[a-z0-9]+)*$")
    if not fm.get("description"):
        err(f"skills/{s}: description مطلوب")
    # المراجع المذكورة في المتن يجب أن توجد، وبصيغة .md حصرًا
    for ref in re.findall(r"\]\((references/[^)]+)\)", body):
        rp = pkg / "skills" / s / ref
        if not rp.exists():
            err(f"skills/{s}: مرجع مفقود {ref}")
        elif rp.suffix != ".md":
            err(f"skills/{s}: المرجع {ref} ليس .md — الاستيراد المحلي ينقل "
                f"ملفات .md فقط، وسيصل الوكيل إلى مرجع غير موجود")
    for extra in (pkg / "skills" / s).rglob("*"):
        if extra.is_file() and extra.suffix not in {".md"}:
            warn(f"skills/{s}: الملف {extra.relative_to(pkg / 'skills' / s)} ليس .md "
                 f"ولن يُنقل في الاستيراد المحلي")

# ── 4. خط المعالجة ────────────────────────────────────────────────────
stages_p = ROOT / "pipelines/qadiya.stages.json"
trans_p = ROOT / "pipelines/qadiya.transitions.json"
if stages_p.exists() and trans_p.exists():
    stages = json.loads(stages_p.read_text(encoding="utf-8"))
    trans = json.loads(trans_p.read_text(encoding="utf-8"))
    keys = {s["key"] for s in stages}

    if sum(1 for s in stages if s["kind"] == "done") == 0:
        err("خط المعالجة: لا مرحلة نهائية (kind: done)")

    for s in stages:
        if s["kind"] not in STAGE_KINDS:
            err(f"مرحلة {s['key']}: kind «{s['kind']}» غير مسموح")
        cfg = s.get("config", {})

        for v in cfg.get("variables", []):
            if not VAR_KEY_RE.match(v["key"]):
                err(f"مرحلة {s['key']}: مفتاح المتغير «{v['key']}» يجب أن يكون "
                    f"لاتينيًا ويطابق ^[A-Za-z][A-Za-z0-9_]*$ (التسمية العربية في label)")
            if v.get("type") == "select" and not v.get("options"):
                err(f"مرحلة {s['key']}: المتغير «{v['key']}» من نوع select بلا options")
            if v.get("type") != "select" and v.get("options"):
                err(f"مرحلة {s['key']}: المتغير «{v['key']}» ليس select ومعه options")

        for fld in ("_assigneeAgentSlug", "_approverAgentSlug"):
            if (slug := cfg.get(fld)) and slug not in agents:
                err(f"مرحلة {s['key']}: {fld}=«{slug}» ليس وكيلًا في الحزمة")
        if bv := cfg.get("_assigneeByVariable"):
            for slug in bv.get("map", {}).values():
                if slug not in agents:
                    err(f"مرحلة {s['key']}: _assigneeByVariable يشير إلى وكيل مجهول «{slug}»")

        if s["kind"] == "review":
            if not cfg.get("_approverAgentSlug"):
                err(f"مرحلة المراجعة {s['key']}: بلا _approverAgentSlug — "
                    f"ستتطلب معتمدًا بشريًا، والمكتب يعمل بلا بشر")
            if not cfg.get("approveToStageKey"):
                err(f"مرحلة المراجعة {s['key']}: approveToStageKey مطلوب")

        for fld in ("approveToStageKey", "rejectToStageKey", "requestChangesToStageKey",
                    "autoAdvanceOnChildrenTerminal"):
            if (dest := cfg.get(fld)) and dest not in keys:
                err(f"مرحلة {s['key']}: {fld} يشير إلى مرحلة غير معرّفة «{dest}»")

    # كل انتقال يشير إلى مراحل موجودة
    allowed: set[tuple[str, str]] = set()
    for t in trans.get("transitions", []):
        f, to = t["fromStageKey"], t["toStageKey"]
        for k in (f, to):
            if k not in keys:
                err(f"انتقال: مرحلة غير معرّفة «{k}»")
        allowed.add((f, to))

    # عند enforceTransitions يجب أن يقابل كل مخرج مراجعة انتقالٌ مسموح،
    # وإلا انحشرت القضية في مرحلة لا مخرج منها.
    if trans.get("enforceTransitions"):
        for s in stages:
            cfg = s.get("config", {})
            for fld in ("approveToStageKey", "rejectToStageKey", "requestChangesToStageKey"):
                if (dest := cfg.get(fld)) and (s["key"], dest) not in allowed:
                    err(f"مرحلة {s['key']}: {fld}→«{dest}» ليس ضمن الانتقالات "
                        f"المسموحة، وenforceTransitions مفعّل ⇒ ستنحشر القضية")
        reachable = {s["key"] for s in stages if s["position"] == min(
            x["position"] for x in stages)}
        changed = True
        while changed:
            changed = False
            for f, to in allowed:
                if f in reachable and to not in reachable:
                    reachable.add(to)
                    changed = True
        for k in keys - reachable:
            err(f"مرحلة «{k}» غير قابلة للوصول من مرحلة البداية")
else:
    warn("تعريفات خط المعالجة غير موجودة — تخطّي فحصها")

# ── 5. إعدادات المكتب ─────────────────────────────────────────────────
office_p = ROOT / "config/office.yaml"
if office_p.exists():
    office = yaml.safe_load(office_p.read_text(encoding="utf-8")) or {}
    if office.get("output", {}).get("draft_watermark") and not \
            office.get("output", {}).get("draft_notice"):
        err("config/office.yaml: draft_watermark مفعّل بلا draft_notice")
else:
    err("config/office.yaml مفقود")

# ── التقرير ───────────────────────────────────────────────────────────
print(f"\n══ تحقق من حزمة المكتب ══")
print(f"{C_D}وكلاء: {len(agents)}   مهارات: {len(skills)}{C_0}\n")
for w in warns:
    print(f"  {C_Y}!{C_0} {w}")
for e in errors:
    print(f"  {C_R}✗{C_0} {e}")
if not errors and not warns:
    print(f"  {C_G}✓ الحزمة سليمة{C_0}")
elif not errors:
    print(f"\n{C_G}✓ الحزمة سليمة{C_0} ({len(warns)} تنبيه)")
else:
    print(f"\n{C_R}✗ {len(errors)} خطأ يمنع الاستيراد{C_0}")
print()
sys.exit(1 if errors else 0)
