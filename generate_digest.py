"""Generate the responsive web index and an email-safe daily digest."""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from jinja2 import BaseLoader, Environment, select_autoescape

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
CATEGORIES = ["Research", "Clinical Trials", "Drug Development", "Organization News", "Regulatory"]


PAGE_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="ALS research, clinical trial, drug development, organization and regulatory intelligence.">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='18' fill='%23087e86'/%3E%3Cpath d='M18 47 28 17h9l10 30h-8l-2-7H27l-2 7zm11-14h6l-3-10z' fill='white'/%3E%3C/svg%3E">
  <title>{{ project.name }}</title>
  <style>
    :root{--ink:#10263c;--muted:#617489;--line:#dbe5ec;--paper:#f4f8fa;--card:#fff;--navy:#0d3655;--teal:#087e86;--teal-soft:#e8f5f4;--gold:#b37a10;--red:#a83a42;--shadow:0 16px 44px rgba(15,48,71,.08)}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;line-height:1.65}
    a{color:inherit}.shell{width:min(1180px,calc(100% - 36px));margin:auto}.masthead{background:linear-gradient(120deg,#082d49 0%,#0b4b65 58%,#087e86 100%);color:#fff;padding:22px 0 52px;position:relative;overflow:hidden}.masthead:after{content:"";position:absolute;right:-120px;top:-180px;width:460px;height:460px;border:1px solid rgba(255,255,255,.16);border-radius:50%;box-shadow:0 0 0 58px rgba(255,255,255,.035),0 0 0 120px rgba(255,255,255,.025)}
    .topline{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;gap:20px}.brand{display:flex;align-items:center;gap:12px;font-weight:760;letter-spacing:.02em}.mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:#fff;color:var(--teal);font-weight:900}.update{font-size:.82rem;color:#cce1e8}
    .hero{position:relative;z-index:1;max-width:790px;padding:66px 0 5px}.kicker{font-size:.75rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#8de1dd}.hero h1{font-size:clamp(2.35rem,5.6vw,4.75rem);line-height:1.02;letter-spacing:-.055em;margin:14px 0 20px}.hero p{margin:0;max-width:680px;color:#d6e9ee;font-size:1.06rem}
    .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:-25px;position:relative;z-index:2}.metric{background:var(--card);border:1px solid rgba(219,229,236,.7);border-radius:16px;padding:19px 20px;box-shadow:var(--shadow)}.metric b{font-size:1.7rem;line-height:1;color:var(--navy);display:block}.metric span{font-size:.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
    .layout{display:grid;grid-template-columns:230px minmax(0,1fr);gap:36px;padding:46px 0 76px}.sidebar{align-self:start;position:sticky;top:20px}.sidebar h2{font-size:.75rem;text-transform:uppercase;letter-spacing:.13em;color:var(--muted);margin:0 0 10px}.sidebar a{display:flex;text-decoration:none;justify-content:space-between;padding:10px 12px;border-radius:9px;font-size:.9rem;color:#385267}.sidebar a:hover{background:#e8f0f3;color:var(--navy)}.sidebar strong{font-size:.72rem;background:#dce8ed;padding:1px 8px;border-radius:20px}.statusbox{margin-top:24px;padding:15px;border:1px solid var(--line);border-radius:12px;background:#eef4f6;font-size:.78rem;color:var(--muted)}.statusline{display:flex;align-items:center;gap:7px;margin-top:7px}.dot{width:7px;height:7px;border-radius:50%;background:#38a169}.dot.error{background:var(--red)}
    .category{scroll-margin-top:18px;margin-bottom:48px}.category-head{display:flex;align-items:end;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:17px}.category-head h2{font-family:Georgia,"Times New Roman",serif;font-size:1.75rem;letter-spacing:-.02em;margin:0}.category-head span{color:var(--muted);font-size:.82rem}.empty{border:1px dashed #bdccd5;border-radius:14px;padding:30px;color:var(--muted);background:rgba(255,255,255,.45)}
    .cards{display:grid;gap:13px}.card{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:22px 24px;box-shadow:0 5px 16px rgba(14,48,71,.035)}.card.new{border-left:4px solid var(--teal)}.card-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.source{font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;font-weight:800;color:var(--teal)}.newtag{font-size:.66rem;font-weight:800;background:var(--teal-soft);color:#07676d;border-radius:20px;padding:2px 8px}.card time{margin-left:auto;font-size:.75rem;color:var(--muted)}.card h3{font-size:1.04rem;line-height:1.45;margin:9px 0 8px}.card h3 a{text-decoration:none}.card h3 a:hover{color:var(--teal);text-decoration:underline}.meta{display:flex;flex-wrap:wrap;gap:5px 15px;color:var(--muted);font-size:.8rem}.abstract{font-size:.86rem;color:#3e5569;margin-top:12px}.abstract summary{cursor:pointer;color:var(--teal);font-weight:700}.abstract p{white-space:pre-line;margin:8px 0 0}.pill{display:inline-block;border-radius:20px;background:#eef3f5;padding:2px 9px;color:#355064}.footer{border-top:1px solid var(--line);padding:24px 0 42px;color:var(--muted);font-size:.8rem}.footer .shell{display:flex;justify-content:space-between;gap:20px}
    @media(max-width:800px){.metrics{grid-template-columns:repeat(2,1fr)}.layout{display:block}.sidebar{position:static;margin-bottom:34px}.sidebar nav{display:flex;overflow:auto;padding-bottom:5px}.sidebar a{white-space:nowrap}.statusbox{display:none}.hero{padding-top:46px}.footer .shell{display:block}}
    @media(max-width:520px){.shell{width:min(100% - 24px,1180px)}.masthead{padding-top:15px}.update{display:none}.hero{padding:42px 0 10px}.metrics{gap:8px;margin-top:-20px}.metric{padding:14px}.metric b{font-size:1.35rem}.layout{padding-top:34px}.card{padding:18px}.card time{width:100%;margin-left:0}.category-head h2{font-size:1.5rem}}
  </style>
</head>
<body>
  <header class="masthead">
    <div class="shell">
      <div class="topline"><div class="brand"><span class="mark">A</span><span>ALS GLOBAL INTELLIGENCE</span></div><div class="update">Updated {{ generated_local }}</div></div>
      <div class="hero"><div class="kicker">Daily research surveillance</div><h1>Signals that move<br>ALS research forward.</h1><p>自动追踪 ALS / MND 新论文、临床试验、药物开发、组织动态与监管信息。来源可追溯，不使用 AI 自动摘要。</p></div>
    </div>
  </header>
  <div class="shell metrics">
    <div class="metric"><b>{{ totals.all }}</b><span>Indexed records</span></div>
    <div class="metric"><b>{{ totals.new }}</b><span>New this run</span></div>
    <div class="metric"><b>{{ totals.research }}</b><span>Research</span></div>
    <div class="metric"><b>{{ totals.trials }}</b><span>Trial records</span></div>
  </div>
  <main class="shell layout">
    <aside class="sidebar">
      <h2>Intelligence streams</h2>
      <nav>{% for category in categories %}<a href="#{{ category|slug }}"><span>{{ category }}</span><strong>{{ grouped[category]|length }}</strong></a>{% endfor %}</nav>
      <div class="statusbox"><strong>Source status</strong>{% for source in status.sources %}<div class="statusline"><i class="dot{% if source.status == 'error' %} error{% endif %}"></i>{{ source.source_id }} · {{ source.status }}</div>{% endfor %}</div>
    </aside>
    <div>
      {% for category in categories %}
      <section class="category" id="{{ category|slug }}">
        <div class="category-head"><h2>{{ category }}</h2><span>{{ grouped[category]|length }} records</span></div>
        {% if grouped[category] %}<div class="cards">
        {% for item in grouped[category] %}
          <article class="card{% if item.is_new %} new{% endif %}">
            <div class="card-top"><span class="source">{{ item.source_name }}</span>{% if item.is_new %}<span class="newtag">NEW</span>{% endif %}<time>{{ item|display_date }}</time></div>
            <h3><a href="{{ item.url }}" target="_blank" rel="noopener noreferrer">{{ item.title }}</a></h3>
            {% if item.pmid %}<div class="meta"><span>{{ item.authors|join(', ')|truncate(180) }}</span><span>{{ item.journal }}</span><span>PMID {{ item.pmid }}</span>{% if item.doi %}<span>DOI {{ item.doi }}</span>{% endif %}</div>{% endif %}
            {% if item.nct_id %}<div class="meta"><span class="pill">{{ item.nct_id }}</span><span>{{ item.sponsor }}</span><span>{{ item.phase|join(' / ')|replace('_',' ') }}</span><span>{{ item.recruitment_status|replace('_',' ') }}</span>{% if item.intervention %}<span>{{ item.intervention|join('; ') }}</span>{% endif %}</div>{% endif %}
            {% if item.abstract %}<details class="abstract"><summary>View abstract</summary><p>{{ item.abstract }}</p></details>{% endif %}
            {% if item.summary %}<p class="abstract">{{ item.summary|truncate(420) }}</p>{% endif %}
          </article>
        {% endfor %}</div>{% else %}<div class="empty">当前尚无此分类记录。启用对应 RSS / website 数据源后会自动显示在这里。</div>{% endif %}
      </section>
      {% endfor %}
    </div>
  </main>
  <footer class="footer"><div class="shell"><span>ALS Global Intelligence · Automated public-source monitoring</span><span>信息仅供科研情报参考，不构成医疗建议。</span></div></footer>
</body>
</html>"""


EMAIL_TEMPLATE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{{ project.name }} Daily Briefing</title></head>
<body style="margin:0;background:#f2f6f8;color:#10263c;font-family:Arial,'Microsoft YaHei',sans-serif;line-height:1.55"><div style="max-width:720px;margin:auto;padding:24px 14px"><div style="background:#0d415d;color:white;padding:28px;border-radius:14px 14px 0 0"><div style="font-size:12px;letter-spacing:1.4px;color:#8de1dd;font-weight:bold">ALS GLOBAL INTELLIGENCE</div><h1 style="font-size:28px;margin:8px 0">Daily Briefing</h1><div style="color:#d5e8ed">{{ generated_local }} · {{ new_items|length }} 条新增</div></div><div style="background:white;padding:26px;border-radius:0 0 14px 14px">
{% if new_items %}{% for category in categories %}{% set items = new_grouped[category] %}{% if items %}<h2 style="font-family:Georgia,serif;font-size:21px;border-bottom:1px solid #dbe5ec;padding-bottom:8px;margin-top:28px">{{ category }}</h2>{% for item in items %}<div style="padding:14px 0;border-bottom:1px solid #edf1f3"><div style="font-size:11px;color:#087e86;font-weight:bold;text-transform:uppercase">{{ item.source_name }} · {{ item|display_date }}</div><h3 style="font-size:16px;line-height:1.4;margin:5px 0"><a style="color:#10263c" href="{{ item.url }}">{{ item.title }}</a></h3>{% if item.nct_id %}<div style="font-size:13px;color:#617489">{{ item.nct_id }} · {{ item.sponsor }} · {{ item.recruitment_status|replace('_',' ') }}</div>{% elif item.pmid %}<div style="font-size:13px;color:#617489">{{ item.journal }} · PMID {{ item.pmid }}</div>{% endif %}</div>{% endfor %}{% endif %}{% endfor %}{% else %}<p>本次运行未发现尚未推送的新内容。</p>{% endif %}
{% set failures = status.sources|selectattr('status','equalto','error')|list %}{% if failures %}<div style="margin-top:24px;padding:12px;background:#fff3f3;border-left:3px solid #a83a42"><strong>数据源提醒</strong><br>{% for source in failures %}{{ source.source_id }}: {{ source.error }}<br>{% endfor %}</div>{% endif %}<p style="font-size:12px;color:#718395;margin-top:28px">自动采集自公开来源；请打开原始链接核实细节。此邮件不构成医疗建议。</p></div></div></body></html>"""


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def slug(value: str) -> str:
    return value.lower().replace(" ", "-")


def display_date(item: dict[str, Any]) -> str:
    return str(
        item.get("last_update_date")
        or item.get("publication_date")
        or item.get("published_date")
        or item.get("collected_at", "")[:10]
        or "Date unavailable"
    )


def clean_rendered_html(value: str) -> str:
    """Keep generated artifacts deterministic and free of trailing whitespace."""
    return "\n".join(line.rstrip() for line in value.splitlines()) + "\n"


def build_context(config: dict[str, Any]) -> dict[str, Any]:
    datasets = [
        load_json(DATA_DIR / "articles.json", {"items": [], "new_keys": []}),
        load_json(DATA_DIR / "trials.json", {"items": [], "new_keys": []}),
        load_json(DATA_DIR / "news.json", {"items": [], "new_keys": []}),
    ]
    new_keys = {key for dataset in datasets for key in dataset.get("new_keys", [])}
    items: list[dict[str, Any]] = []
    for dataset in datasets:
        for raw in dataset.get("items", []):
            item = dict(raw)
            item["is_new"] = item.get("event_key") in new_keys
            items.append(item)
    grouped = {category: [] for category in CATEGORIES}
    for item in items:
        category = item.get("category", "Organization News")
        grouped.setdefault(category, []).append(item)
    new_items = [item for item in items if item["is_new"]]
    new_grouped = {category: [item for item in grouped.get(category, []) if item["is_new"]] for category in CATEGORIES}
    timezone_name = config.get("project", {}).get("timezone", "Asia/Shanghai")
    now = datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name))
    return {
        "project": config.get("project", {"name": "ALS Global Intelligence"}),
        "categories": CATEGORIES,
        "grouped": grouped,
        "new_grouped": new_grouped,
        "new_items": new_items,
        "generated_local": now.strftime("%Y-%m-%d %H:%M %Z"),
        "status": load_json(DATA_DIR / "run_status.json", {"sources": []}),
        "totals": {
            "all": len(items),
            "new": len(new_items),
            "research": len(grouped["Research"]),
            "trials": len(grouped["Clinical Trials"]),
        },
    }


def render(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    context = build_context(config)
    environment = Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )
    environment.filters["slug"] = slug
    environment.filters["display_date"] = display_date
    DOCS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    page = clean_rendered_html(environment.from_string(PAGE_TEMPLATE).render(**context))
    email_body = clean_rendered_html(environment.from_string(EMAIL_TEMPLATE).render(**context))
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8", newline="\n")
    (DATA_DIR / "email_digest.html").write_text(email_body, encoding="utf-8", newline="\n")
    print(
        f"Generated docs/index.html with {context['totals']['all']} records "
        f"({context['totals']['new']} new)."
    )
    return context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "sources.yaml")
    args = parser.parse_args()
    try:
        render(args.config.resolve())
        return 0
    except Exception as exc:
        print(f"ERROR: digest generation failed: {html.escape(str(exc))}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
