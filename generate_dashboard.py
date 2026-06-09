"""
generate_dashboard.py
---------------------
reads the db and writes index.html, spreadsheet.html, and data.json
(run after adding new records)

    python generate_dashboard.py
    python generate_dashboard.py --out-dir docs/
    python generate_dashboard.py --db data/usecases.db --out-dir 
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scrapers"))
from scraper_base import get_db, DB_PATH

ROOT_DIR = Path(__file__).resolve().parent


# ── data ───────────────────────────────────────────────────────────────────────

def load_data(db_path):
    conn = get_db(db_path)
    conn.execute("PRAGMA query_only = ON;")
    records = conn.execute("""
        SELECT id, title, organisation, country, date_published,
               source_name, source_category, summary, url,
               task_type, effect_type
        FROM use_cases
        WHERE source_name != 'Test'
        ORDER BY date_published DESC
    """).fetchall()
    data = [dict(r) for r in records]

    COUNTRY_NORM = {
        "USA": "United States", "U.S.": "United States", "US": "United States",
        "UK":  "United Kingdom", "U.K.": "United Kingdom",
    }
    EXCLUDE_REGIONS = {"Global", "Africa", "Europe", "Asia", "Latin America", "Middle East"}

    by_year        = {}
    by_country     = {}
    by_category    = {}
    by_source      = {}
    by_task_type   = {}
    by_effect_type = {}
    source_detail  = {}

    for r in data:
        yr = (r["date_published"] or "")[:4]
        if yr and yr.isdigit() and 2010 <= int(yr) <= 2030:
            by_year[yr] = by_year.get(yr, 0) + 1
        for c in (r["country"] or "").split(","):
            c = COUNTRY_NORM.get(c.strip(), c.strip())
            if c and c not in EXCLUDE_REGIONS:
                by_country[c] = by_country.get(c, 0) + 1
        cat = (r["source_category"] or "").strip()
        if cat:
            by_category[cat] = by_category.get(cat, 0) + 1
        src = (r["source_name"] or "").strip()
        cat = (r["source_category"] or "").strip()
        if src:
            by_source[src] = by_source.get(src, 0) + 1
            if src not in source_detail:
                source_detail[src] = {"category": cat, "count": 0}
            source_detail[src]["count"] += 1
        tt = (r["task_type"] or "").strip()
        if tt:
            by_task_type[tt] = by_task_type.get(tt, 0) + 1
        et = (r["effect_type"] or "").strip()
        if et:
            by_effect_type[et] = by_effect_type.get(et, 0) + 1

    def _build_timeline(data, field, names):
        year_buckets = {}
        for r in data:
            yr = (r["date_published"] or "")[:4]
            if not yr or not yr.isdigit() or int(yr) < 2014 or int(yr) > 2026:
                continue
            val = (r.get(field) or "").strip()
            if not val:
                continue
            if yr not in year_buckets:
                year_buckets[yr] = {}
            year_buckets[yr][val] = year_buckets[yr].get(val, 0) + 1
        years = sorted(year_buckets.keys())
        return {
            "years":      years,
            "categories": {n: [year_buckets.get(yr, {}).get(n, 0) for yr in years] for n in names},
        }

    task_names   = [t for t, _ in sorted(by_task_type.items(),   key=lambda x: -x[1])]
    effect_names = [e for e, _ in sorted(by_effect_type.items(), key=lambda x: -x[1])]

    stats = {
        "total":          len(data),
        "by_year":        sorted(by_year.items()),
        "top_countries":  sorted(by_country.items(),  key=lambda x: -x[1]),
        "top_categories": sorted(by_category.items(), key=lambda x: -x[1])[:12],
        "top_sources":    sorted(by_source.items(),   key=lambda x: -x[1])[:15],
        "source_names":   sorted(by_source.keys()),
        "sources_list":   sorted(
            [{"name": k, "category": v["category"], "count": v["count"]}
             for k, v in source_detail.items()],
            key=lambda x: -x["count"]
        ),
        "task_by_year":   _build_timeline(data, "task_type",   task_names),
        "effect_by_year": _build_timeline(data, "effect_type", effect_names),
    }
    conn.close()
    return data, stats


# ── index.html template ────────────────────────────────────────────────────────

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Use Cases in News Organisations</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;1,400;1,600&family=Source+Sans+3:ital,wght@0,300;0,400;0,600;1,300&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --paper:   #f7f5f0;
  --ink:     #002147;
  --rust:    #b65536;
  --rust-lt: rgba(182,85,54,0.08);
  --ash:     #5c6577;
  --rule:    #dce2ea;
  --card:    #faf9f6;
  --mono:    'JetBrains Mono', monospace;
  --sans:    'Source Sans 3', sans-serif;
  --serif:   'Playfair Display', serif;
  --green:   #2a8d46;
  --blue:    #002147;
  --amber:   #cc7722;
  --radius:  2px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }

body {
  font-family: var(--sans);
  background: var(--paper);
  color: var(--ink);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

.grain {
  position: fixed; inset: 0; pointer-events: none; z-index: 9999;
  opacity: 0.03;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

.fade-up {
  opacity: 0; transform: translateY(24px);
  transition: opacity 0.6s cubic-bezier(0.22,1,0.36,1), transform 0.6s cubic-bezier(0.22,1,0.36,1);
}
.fade-up.visible { opacity: 1; transform: translateY(0); }

.inst-attr {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.05em;
  color: var(--ash); margin-top: 20px;
}
.inst-attr a { color: var(--ash); text-decoration: none; border-bottom: 1px solid var(--rule); }
.inst-attr a:hover { color: var(--rust); border-bottom-color: var(--rust); }

nav {
  position: sticky; top: 0; z-index: 100;
  background: #002147;
  border-bottom: 1px solid rgba(255,255,255,0.12);
  padding: 0 32px;
}
.nav-inner {
  max-width: 1280px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
  height: 48px;
}
.nav-brand {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.1em;
  text-transform: uppercase; color: white; text-decoration: none;
  display: flex; align-items: center; gap: 10px;
}
.brand-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--rust);
  animation: pulse 3s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity: 0.6; transform: scale(1); } 50% { opacity: 1; transform: scale(1.2); } }
.nav-meta { font-family: var(--mono); font-size: 10px; color: rgba(255,255,255,0.45); letter-spacing: 0.05em; }
.nav-links { display: flex; align-items: center; gap: 20px; }
.nav-link {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em;
  text-transform: uppercase; color: rgba(255,255,255,0.65); text-decoration: none;
  transition: color 0.15s;
}
.nav-link:hover { color: white; }
.nav-link.active { color: white; }

.hero {
  max-width: 1280px; margin: 0 auto;
  padding: 72px 32px 56px;
  border-bottom: 1px solid var(--rule);
}
.hero-eyebrow {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.15em;
  text-transform: uppercase; color: var(--rust); margin-bottom: 20px;
  display: flex; align-items: center; gap: 10px;
}
.hero-eyebrow::after {
  content: ''; flex: 1; max-width: 48px; height: 1px; background: var(--rust); opacity: 0.4;
}
.hero h1 {
  font-family: var(--serif); font-size: clamp(36px, 5vw, 64px);
  font-weight: 400; line-height: 1.05; letter-spacing: -0.01em;
  color: var(--ink); margin-bottom: 20px;
}
.hero h1 em { font-style: italic; color: var(--rust); }
.hero-sub {
  font-size: 15px; color: var(--ash); line-height: 1.6; max-width: 560px;
  margin-bottom: 32px;
}
.figure-note {
  margin-top: 16px; padding: 12px 16px;
  background: var(--card); border-left: 3px solid var(--rule);
  font-size: 12.5px; color: var(--ash); line-height: 1.65;
}
.figure-note strong { color: var(--ink); font-weight: 600; }

.methods-section { border-top: 1px solid var(--rule); padding: 64px 32px 80px; }
.methods-inner { max-width: 1280px; margin: 0 auto; }
.methods-body { max-width: 780px; margin-top: 24px; }
.methods-body p { font-size: 14.5px; color: var(--ash); line-height: 1.8; margin-bottom: 16px; }
.methods-body p:last-child { margin-bottom: 0; }
.methods-body strong { color: var(--ink); font-weight: 600; }

.sources-section { border-top: 1px solid var(--rule); padding: 64px 32px 80px; background: var(--card); }
.sources-inner { max-width: 1280px; margin: 0 auto; }
.sources-table { width: 100%; border-collapse: collapse; margin-top: 24px; }
.sources-table th { text-align: left; padding: 8px 16px; font-family: var(--mono); font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ash); border-bottom: 2px solid var(--rule); }
.sources-table td { padding: 10px 16px; font-size: 13px; color: var(--ink); border-bottom: 1px solid var(--rule); vertical-align: middle; }
.sources-table tr:last-child td { border-bottom: none; }
.src-count-cell { font-family: var(--mono); font-size: 11px; color: var(--ash); text-align: right; }
.src-cat { display: inline-block; padding: 2px 8px; border-radius: 2px; font-family: var(--mono); font-size: 9px; letter-spacing: 0.04em; }
.src-cat-academic { background: #eef2fb; color: #1a4b9a; border: 1px solid #c5d4f0; }
.src-cat-industry  { background: #fdf3e8; color: #8a4a0a; border: 1px solid #f0d5b0; }
.src-cat-curated   { background: #f2ebfb; color: #5b1fa8; border: 1px solid #d8c4f2; }
.src-cat-database  { background: var(--rust-lt); color: var(--rust); border: 1px solid rgba(182,85,54,0.2); }

.stats-band { border-bottom: 1px solid var(--rule); background: var(--card); }
.stats-inner {
  max-width: 1280px; margin: 0 auto; padding: 0 32px;
  display: grid; grid-template-columns: repeat(5, 1fr);
}
.stat-cell { padding: 32px 24px; text-align: center; border-right: 1px solid var(--rule); }
.stat-cell:last-child { border-right: none; }
.stat-num {
  font-family: var(--serif); font-size: 48px; line-height: 1;
  color: var(--rust); display: block; margin-bottom: 6px;
}
.stat-label {
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.15em;
  text-transform: uppercase; color: var(--ash);
}

.divider { height: 1px; background: linear-gradient(to right, transparent, var(--rule), transparent); }

.layout {
  max-width: 1280px; margin: 0 auto; padding: 0 32px;
  display: grid; grid-template-columns: 260px 1fr;
  gap: 0 40px; min-height: 60vh;
}

.sidebar {
  padding: 32px 0 32px;
  position: sticky; top: 48px;
  max-height: calc(100vh - 48px);
  overflow-y: auto; overflow-x: hidden;
  border-right: 1px solid var(--rule);
  padding-right: 32px;
}
.sidebar::-webkit-scrollbar { width: 3px; }
.sidebar::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 2px; }
.sidebar-section { margin-bottom: 28px; }
.sidebar-label {
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.15em;
  text-transform: uppercase; color: var(--ash); margin-bottom: 10px; display: block;
}

.search-wrap { position: relative; }
.search-input {
  width: 100%; padding: 8px 12px 8px 34px;
  border: 1px solid var(--rule); border-radius: var(--radius);
  background: white; font-family: var(--sans); font-size: 13px;
  color: var(--ink); outline: none; transition: border-color 0.2s;
}
.search-input:focus { border-color: var(--rust); }
.search-icon {
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  color: var(--ash); font-size: 14px; pointer-events: none;
}

.year-chart { display: flex; align-items: flex-end; gap: 4px; height: 60px; margin-top: 8px; }
.year-bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; cursor: pointer; }
.year-bar {
  width: 100%; background: var(--rule); border-radius: 2px 2px 0 0;
  transition: background 0.2s, transform 0.2s; min-height: 3px; transform-origin: bottom;
}
.year-bar-wrap:hover .year-bar { background: var(--rust); transform: scaleY(1.05); }
.year-bar-wrap.active .year-bar { background: var(--rust); }
.year-label { font-family: var(--mono); font-size: 8px; color: var(--ash); transition: color 0.2s; }
.year-bar-wrap.active .year-label, .year-bar-wrap:hover .year-label { color: var(--rust); }

.filter-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 20px;
  border: 1px solid var(--rule); background: var(--card);
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.03em;
  color: var(--ash); cursor: pointer; transition: all 0.15s;
  margin: 2px; word-break: break-word;
}
.filter-pill:hover { border-color: var(--rust); color: var(--rust); background: var(--rust-lt); }
.filter-pill.active { background: var(--rust); border-color: var(--rust); color: white; }
.filter-pill .pill-count { font-size: 9px; opacity: 0.7; background: rgba(0,0,0,0.1); border-radius: 10px; padding: 0 5px; flex-shrink: 0; }
.filter-pill.active .pill-count { background: rgba(255,255,255,0.25); opacity: 1; }
.pill-group { display: flex; flex-wrap: wrap; gap: 2px; }

.reset-btn {
  width: 100%; padding: 8px; border: 1px solid var(--rule);
  border-radius: var(--radius); background: none;
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--ash); cursor: pointer;
  transition: all 0.15s; margin-top: 8px;
}
.reset-btn:hover { background: var(--rust); color: white; border-color: var(--rust); }

.main { padding: 32px 0; min-width: 0; }

.toolbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 20px; padding-bottom: 16px;
  border-bottom: 1px solid var(--rule);
}
.result-count { font-family: var(--mono); font-size: 11px; color: var(--ash); }
.result-count strong { font-size: 16px; color: var(--ink); font-weight: 500; }
.sort-select {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.04em;
  border: 1px solid var(--rule); border-radius: var(--radius);
  padding: 6px 10px; background: white; color: var(--ash); cursor: pointer;
  text-transform: uppercase;
}

.active-filter-bar {
  display: none; align-items: center; gap: 10px;
  background: var(--rust); color: white;
  padding: 10px 16px; border-radius: var(--radius);
  margin-bottom: 16px;
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.04em;
}
.active-filter-bar.show { display: flex; }
.filter-bar-label { text-transform: uppercase; opacity: 0.7; }
.filter-bar-value { font-weight: 500; text-transform: uppercase; }
.filter-bar-clear {
  margin-left: auto; background: rgba(255,255,255,0.2); border: none;
  color: white; padding: 4px 12px; border-radius: var(--radius);
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.05em;
  text-transform: uppercase; cursor: pointer; transition: background 0.15s;
}
.filter-bar-clear:hover { background: rgba(255,255,255,0.35); }

.cards { display: flex; flex-direction: column; gap: 1px; }

.card {
  background: white; border: 1px solid var(--rule);
  border-radius: var(--radius); padding: 20px 24px;
  display: grid; grid-template-columns: 1fr auto;
  gap: 8px 16px; align-items: start;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
  position: relative; overflow: hidden;
}
.card::before {
  content: ''; position: absolute; top: 0; left: 0;
  width: 3px; height: 100%; background: transparent; transition: background 0.2s;
}
.card:hover { border-color: var(--rust); box-shadow: 0 4px 20px rgba(182,85,54,0.08); transform: translateX(2px); }
.card:hover::before { background: var(--rust); }
.card-title { font-family: var(--serif); font-size: 16px; font-weight: 400; line-height: 1.4; color: var(--ink); }
.card-title a { color: inherit; text-decoration: none; transition: color 0.2s; }
.card-title a:hover { color: var(--rust); }
.card-date { grid-column: 2; grid-row: 1; font-family: var(--mono); font-size: 10px; color: var(--ash); white-space: nowrap; padding-top: 2px; }
.card-meta { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.card-org { font-size: 12px; color: var(--ash); margin-right: 4px; }
.tag {
  display: inline-block; padding: 2px 8px; border-radius: 12px;
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.04em;
  text-transform: uppercase; border: 1px solid var(--rule);
  background: var(--card); color: var(--ash);
}
.tag.country { background: #f0f7ff; border-color: #cce0ff; color: #1a5db0; }
.tag.source  { background: #f0f9f2; border-color: #bbe5c3; color: #236634; }
.tag.cat     { background: var(--rust-lt); border-color: rgba(182,85,54,0.2); color: var(--rust); }
.tag.task    { background: #f0eef8; border-color: #c5bcec; color: #5b3ea6; }
.tag.effect  { background: #f0f4ff; border-color: #c5d4f0; color: #1a4b9a; }
.tag.effect-efficiency                { background: rgba(182,85,54,0.08); border-color: rgba(182,85,54,0.25); color: #b65536; }
.tag.effect-effectiveness_and_scaling { background: #eef2fb; border-color: #c5d4f0; color: #1a4b9a; }
.tag.effect-optimisation              { background: #eaf5ed; border-color: #c3e0cb; color: #236634; }

.state-msg { padding: 80px 24px; text-align: center; color: var(--ash); }
.state-msg p:first-child { font-family: var(--serif); font-size: 28px; color: var(--ink); margin-bottom: 10px; font-style: italic; }
.state-msg p { font-size: 13px; }

.pagination { padding: 32px 0 0; display: flex; justify-content: center; gap: 4px; }
.page-btn {
  padding: 7px 14px; border: 1px solid var(--rule); background: white;
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.04em;
  cursor: pointer; border-radius: var(--radius); color: var(--ash); transition: all 0.15s;
}
.page-btn:hover:not(:disabled) { background: var(--ink); color: white; border-color: var(--ink); }
.page-btn.active { background: var(--rust); color: white; border-color: var(--rust); }
.page-btn:disabled { opacity: 0.25; cursor: not-allowed; }

.insights-section { border-top: 1px solid var(--rule); background: var(--card); padding: 64px 32px 80px; }
.insights-inner { max-width: 1280px; margin: 0 auto; }
.insights-header { margin-bottom: 48px; }
.insights-title { font-family: var(--serif); font-size: clamp(28px, 3vw, 42px); font-weight: 400; line-height: 1.1; margin-bottom: 14px; margin-top: 12px; }
.insights-sub { font-size: 14px; color: var(--ash); max-width: 600px; line-height: 1.6; }

.timeline-block { margin-bottom: 52px; }
.timeline-block:last-of-type { margin-bottom: 0; }
.timeline-block-label {
  font-family: var(--sans); font-size: 16px; font-weight: 600;
  color: var(--ink); margin-bottom: 20px;
}

.timeline-chart {
  background: white; border: 1px solid var(--rule); border-radius: var(--radius);
  padding: 32px 32px 24px; margin-bottom: 40px; overflow-x: auto;
}
.timeline-years { display: flex; gap: 0; margin-bottom: 12px; }
.timeline-year-label { flex: 1; font-family: var(--mono); font-size: 10px; letter-spacing: 0.06em; color: var(--ash); text-align: center; min-width: 60px; }
.timeline-bars { display: flex; gap: 6px; align-items: flex-end; height: 220px; border-bottom: 1px solid var(--rule); margin-bottom: 20px; min-width: 540px; }
.timeline-bar-group { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: stretch; min-width: 60px; cursor: pointer; position: relative; height: 100%; }
.timeline-segment { width: 100%; flex-shrink: 0; }
.timeline-bar-group:hover .timeline-segment { opacity: 0.85; }
.bar-tooltip {
  display: none; position: fixed;
  background: var(--ink); color: white; border-radius: var(--radius);
  padding: 10px 14px; width: 190px; z-index: 9000;
  font-family: var(--mono); font-size: 9px; line-height: 1.8; letter-spacing: 0.03em;
  pointer-events: none; box-shadow: 0 4px 16px rgba(0,0,0,0.25);
}
.tooltip-year { font-size: 11px; font-weight: 500; margin-bottom: 4px; opacity: 0.7; }
.tooltip-row { display: flex; justify-content: space-between; gap: 8px; }
.tooltip-swatch { width: 8px; height: 8px; border-radius: 1px; flex-shrink: 0; margin-top: 2px; }
.timeline-legend { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 9px; letter-spacing: 0.04em; color: var(--ash); text-transform: uppercase; }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }

.annotation-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 48px; }
.annotation-card {
  background: white; border: 1px solid var(--rule); border-radius: var(--radius);
  padding: 20px; position: relative; overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.annotation-card::before { content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 3px; background: var(--rust); opacity: 0.5; }
.annotation-card:hover { border-color: var(--rust); box-shadow: 0 4px 16px rgba(182,85,54,0.08); }
.annotation-year { font-family: var(--mono); font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--rust); margin-bottom: 6px; }
.annotation-label { font-family: var(--serif); font-size: 16px; font-style: italic; color: var(--ink); margin-bottom: 10px; }
.annotation-text { font-size: 12px; color: var(--ash); line-height: 1.6; }

.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
.chart-panel { background: white; border: 1px solid var(--rule); border-radius: var(--radius); padding: 24px; }
.chart-panel-label { font-family: var(--sans); font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 20px; }
.chart-panel-scroll { max-height: 520px; overflow-y: auto; padding-right: 4px; }
.chart-panel-scroll::-webkit-scrollbar { width: 3px; }
.chart-panel-scroll::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 2px; }
.bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.bar-label { font-size: 11px; color: var(--ink); width: 190px; min-width: 190px; max-width: 190px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; height: 16px; background: var(--rule); border-radius: 2px; overflow: hidden; min-width: 60px; }
.bar-fill { height: 100%; border-radius: 2px; background: var(--rust); transform-origin: left; transform: scaleX(0); transition: transform 1s cubic-bezier(0.22,1,0.36,1); }
.bar-fill.animated { transform: scaleX(1); }
.bar-count { font-family: var(--mono); font-size: 10px; color: var(--ash); min-width: 30px; text-align: right; }

footer { border-top: 1px solid var(--rule); padding: 32px; font-family: var(--mono); font-size: 10px; color: var(--ash); text-align: center; letter-spacing: 0.05em; }
.footer-inner { max-width: 1280px; margin: 0 auto; }

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { position: static; max-height: none; border-right: none; border-bottom: 1px solid var(--rule); padding-right: 0; padding-bottom: 24px; }
  .stats-inner { grid-template-columns: repeat(3, 1fr); }
  .stat-cell:nth-child(3) { border-right: none; }
  .annotation-grid { grid-template-columns: 1fr 1fr; }
  .chart-grid { grid-template-columns: 1fr; }
  .insights-section { padding: 48px 24px 64px; }
  .hero { padding: 48px 24px 40px; }
  .layout { padding: 0 24px; }
  nav { padding: 0 24px; }
}
@media (max-width: 560px) {
  .stats-inner { grid-template-columns: 1fr 1fr; }
  .annotation-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="grain"></div>

<nav>
  <div class="nav-inner">
    <a class="nav-brand" href="#">
      <span class="brand-dot"></span>
      AI in News Organisations
    </a>
    <div class="nav-links">
      <a class="nav-link active" href="index.html">Overview</a>
      <a class="nav-link" href="spreadsheet.html">Spreadsheet</a>
      <span class="nav-meta" id="generatedAt"></span>
    </div>
  </div>
</nav>

<section class="hero fade-up">
  <p class="inst-attr"><a href="https://reutersinstitute.politics.ox.ac.uk" target="_blank" rel="noopener">Reuters Institute for the Study of Journalism</a> · University of Oxford</p>
  <h1>AI Use Cases in<br><em>News Organisations</em></h1>
  <p class="hero-sub">A dataset of publicly documented AI use cases in news organisations worldwide, drawn from industry publications, research databases, and curated reports.</p>
</section>

<div class="stats-band">
  <div class="stats-inner" id="statsRow">
    <div class="stat-cell"><span class="stat-num">—</span><span class="stat-label">Loading</span></div>
  </div>
</div>

<div class="divider"></div>

<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-section">
      <span class="sidebar-label">Search</span>
      <div class="search-wrap">
        <span class="search-icon">⌕</span>
        <input class="search-input" type="text" id="searchInput" placeholder="Organisation, keyword…">
      </div>
    </div>

    <div class="sidebar-section">
      <span class="sidebar-label">Year</span>
      <div class="year-chart" id="yearChart"></div>
    </div>

    <div class="sidebar-section">
      <span class="sidebar-label">Type</span>
      <div class="pill-group" id="categoryFilters"></div>
    </div>

    <div class="sidebar-section">
      <span class="sidebar-label">Source</span>
      <div class="pill-group" id="sourceFilters"></div>
    </div>

    <div class="sidebar-section">
      <span class="sidebar-label">Country</span>
      <div class="pill-group" id="countryFilters"></div>
    </div>

    <button class="reset-btn" id="resetBtn">↺ Reset all filters</button>
  </aside>

  <main class="main">
    <div class="toolbar">
      <div class="result-count" id="resultCount">Loading…</div>
      <select class="sort-select" id="sortSelect">
        <option value="date_desc">Newest first</option>
        <option value="date_asc">Oldest first</option>
        <option value="title_asc">Title A–Z</option>
        <option value="org_asc">Organisation A–Z</option>
      </select>
    </div>

    <div class="active-filter-bar" id="activeFilterBar">
      <span class="filter-bar-label">Filtered by</span>
      <span class="filter-bar-value" id="activeFilterLabel"></span>
      <button class="filter-bar-clear" id="filterBarClear">Clear all</button>
    </div>

    <div class="cards" id="cards">
      <div class="state-msg"><p>Loading data…</p><p>Fetching use cases</p></div>
    </div>
    <div class="pagination" id="pagination"></div>
  </main>
</div>

<section class="insights-section">
  <div class="insights-inner">
    <div class="insights-header fade-up">
      <div class="hero-eyebrow">Insights</div>
      <h2 class="insights-title">How AI adoption has evolved</h2>
      <p class="insights-sub">Distribution of AI use cases across <span id="insightsTotalYears"></span> years of documented cases, broken down by functional task type and primary effect delivered.</p>
    </div>

    <div class="timeline-block fade-up">
      <div class="timeline-block-label">What AI is doing — by task type</div>
      <div class="timeline-chart" id="taskTimeline">
        <div class="timeline-years" id="taskTimelineYears"></div>
        <div class="timeline-bars" id="taskTimelineBars"></div>
        <div class="timeline-legend" id="taskTimelineLegend"></div>
      </div>
    </div>

    <div class="timeline-block fade-up">
      <div class="timeline-block-label">What AI is delivering — by effect type</div>
      <div class="timeline-chart" id="effectTimeline">
        <div class="timeline-years" id="effectTimelineYears"></div>
        <div class="timeline-bars" id="effectTimelineBars"></div>
        <div class="timeline-legend" id="effectTimelineLegend"></div>
      </div>
      <div class="figure-note"><strong>Efficiency</strong> — AI reduces time, cost, or effort for tasks that were previously done manually. <strong>Effectiveness &amp; scaling</strong> — AI enables tasks or volumes not previously possible, or dramatically expands what a team can produce. <strong>Optimisation</strong> — AI improves quality, targeting, personalisation, or distribution without fundamentally changing the underlying task.</div>
    </div>

    <div class="chart-grid fade-up">
      <div class="chart-panel">
        <div class="chart-panel-label">Records by source</div>
        <div id="catChart"></div>
      </div>
      <div class="chart-panel">
        <div class="chart-panel-label">All countries</div>
        <div class="chart-panel-scroll"><div id="countryChart"></div></div>
      </div>
    </div>
  </div>
</section>

<section class="methods-section">
  <div class="methods-inner">
    <div class="fade-up">
      <div class="hero-eyebrow">Methodology</div>
      <h2 class="insights-title">How this dataset was built</h2>
    </div>
    <div class="methods-body fade-up">
      <p>This dataset was compiled by systematically scraping and analysing publicly available reporting on AI adoption in news organisations from 16 industry, research, and curated sources. Each record represents a documented AI use case — a specific deployment or application of AI technology by an identifiable news organisation, as reported in trade publications, research databases, industry reports, or academic outlets.</p>
      <p>Use cases were identified through automated scraping of source websites, then filtered using a language model (GPT-4o-mini) to exclude articles that did not describe a concrete AI application by a news organisation. Cases were then automatically classified by functional task type (what the AI does) and primary effect type (what benefit it delivers), with uncertain classifications flagged for low confidence.</p>
      <p><strong>Important limitations.</strong> This dataset captures only what has been publicly documented, in English, across a specific set of monitored sources. Many deployments go unreported, while high-profile organisations attract disproportionate coverage. Documentation standards and terminology vary significantly across outlets, regions, and time periods. The dataset should be read as a partial and illustrative snapshot of documented AI adoption — not a definitive map of the field.</p>
    </div>
  </div>
</section>

<section class="sources-section">
  <div class="sources-inner">
    <div class="fade-up">
      <div class="hero-eyebrow">Sources</div>
      <h2 class="insights-title">Data sources</h2>
      <p class="insights-sub">The <span id="sourcesTotal"></span> sources below span industry reporting, curated databases, and academic and practitioner research.</p>
    </div>
    <div class="fade-up">
      <table class="sources-table">
        <thead>
          <tr>
            <th>Source</th>
            <th>Category</th>
            <th style="text-align:right">Records</th>
          </tr>
        </thead>
        <tbody id="sourcesTableBody"></tbody>
      </table>
    </div>
  </div>
</section>

<footer>
  <div class="footer-inner">
    Reuters Institute for the Study of Journalism · University of Oxford · AI use cases in news organisations
  </div>
</footer>

<script>
var ALL_DATA = [];
var STATS = {};
var filtered = [];
var currentPage = 1;
var PAGE_SIZE = 25;
var activeYear = null;
var activeCategories = new Set();
var activeSources = new Set();
var activeCountries = new Set();
var searchQuery = '';

function esc(s) {
  var el = document.createElement('div');
  el.textContent = String(s || '');
  return el.innerHTML;
}

var observer = new IntersectionObserver(function(entries) {
  entries.forEach(function(e) {
    if (e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); }
  });
}, { threshold: 0.1 });
document.querySelectorAll('.fade-up').forEach(function(el) { observer.observe(el); });

function init() {
  (function() {
    var payload = __INLINE_DATA__;
    ALL_DATA = payload.records;
    STATS = payload.stats;
    var g = document.getElementById('generatedAt');
    if (g) g.textContent = 'Updated ' + payload.generated_at;
    filtered = ALL_DATA.slice();
    buildStats();
    buildYearChart();
    buildFilters('categoryFilters', 'categories', activeCategories, toggleCategory);
    buildFilters('sourceFilters', 'sources', activeSources, toggleSource);
    buildFilters('countryFilters', 'countries', activeCountries, toggleCountry);
    buildCharts();
    applyFilters();
  })();

  document.getElementById('searchInput').addEventListener('input', function(e) {
    searchQuery = e.target.value.toLowerCase();
    currentPage = 1; applyFilters();
  });
  document.getElementById('sortSelect').addEventListener('change', render);
  document.getElementById('resetBtn').addEventListener('click', resetAll);
  document.getElementById('filterBarClear').addEventListener('click', resetAll);
}

function buildStats() {
  var orgs = {}, countries = {}, sources = {}, years = {};
  ALL_DATA.forEach(function(d) {
    if (d.organisation) orgs[d.organisation] = true;
    if (d.source_name) sources[d.source_name] = true;
    var yr = (d.date_published || '').slice(0, 4);
    if (yr && parseInt(yr) > 2010) years[yr] = true;
    (d.country || '').split(',').forEach(function(c) { c = c.trim(); if (c) countries[c] = true; });
  });
  document.getElementById('statsRow').innerHTML =
    mkStat(ALL_DATA.length, 'Use Cases') +
    mkStat(Object.keys(orgs).length, 'Organisations') +
    mkStat(Object.keys(countries).length, 'Countries') +
    mkStat(Object.keys(sources).length, 'Sources') +
    mkStat(Object.keys(years).length, 'Years Covered');
}
function mkStat(n, label) {
  return '<div class="stat-cell fade-up visible"><span class="stat-num">' + n +
    '</span><span class="stat-label">' + label + '</span></div>';
}

function buildYearChart() {
  var years = STATS.by_year || [];
  if (!years.length) return;
  var maxN = 0;
  years.forEach(function(y) { if (y[1] > maxN) maxN = y[1]; });
  var html = '';
  years.forEach(function(item) {
    var yr = item[0], n = item[1];
    var h = Math.max(4, Math.round(n / maxN * 52));
    var cls = activeYear === yr ? 'year-bar-wrap active' : 'year-bar-wrap';
    html += '<div class="' + cls + '" data-year="' + yr + '" title="' + yr + ': ' + n + ' cases">' +
            '<div class="year-bar" style="height:' + h + 'px"></div>' +
            '<div class="year-label">' + yr.slice(2) + '</div></div>';
  });
  var c = document.getElementById('yearChart');
  c.innerHTML = html;
  c.querySelectorAll('.year-bar-wrap').forEach(function(el) {
    el.addEventListener('click', function() { toggleYear(el.getAttribute('data-year')); });
  });
}
function toggleYear(yr) {
  activeYear = activeYear === yr ? null : yr;
  buildYearChart(); currentPage = 1; applyFilters();
}

function buildFilters(id, mode, activeSet, fn) {
  var counts = {};
  ALL_DATA.forEach(function(r) {
    var vals = mode === 'categories'
      ? (r.source_category ? [r.source_category] : [])
      : mode === 'sources' ? (r.source_name ? [r.source_name] : [])
      : (r.country || '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
    vals.forEach(function(v) { if (v) counts[v] = (counts[v] || 0) + 1; });
  });
  var sorted = Object.keys(counts)
    .map(function(k) { return [k, counts[k]]; })
    .sort(function(a, b) { return b[1] - a[1]; }).slice(0, 18);
  var html = '';
  sorted.forEach(function(item) {
    var val = item[0], count = item[1];
    var cls = 'filter-pill' + (activeSet.has(val) ? ' active' : '');
    html += '<button class="' + cls + '" data-val="' + esc(val) + '">' +
            esc(val) + '<span class="pill-count">' + count + '</span></button>';
  });
  var container = document.getElementById(id);
  container.innerHTML = html;
  container.querySelectorAll('.filter-pill').forEach(function(btn) {
    btn.addEventListener('click', function() { fn(btn.getAttribute('data-val')); });
  });
}
function toggleCategory(v) { toggle(v, activeCategories); buildFilters('categoryFilters', 'categories', activeCategories, toggleCategory); currentPage = 1; applyFilters(); }
function toggleSource(v)   { toggle(v, activeSources);   buildFilters('sourceFilters',   'sources',    activeSources,    toggleSource);   currentPage = 1; applyFilters(); }
function toggleCountry(v)  { toggle(v, activeCountries);  buildFilters('countryFilters',  'countries',  activeCountries,  toggleCountry);  currentPage = 1; applyFilters(); }
function toggle(v, set) { if (set.has(v)) { set.delete(v); } else { set.add(v); } }

function updateFilterBar() {
  var parts = [];
  if (activeYear) parts.push(activeYear);
  activeCategories.forEach(function(v) { parts.push(v); });
  activeSources.forEach(function(v) { parts.push(v); });
  activeCountries.forEach(function(v) { parts.push(v); });
  if (searchQuery) parts.push('"' + searchQuery + '"');
  var bar = document.getElementById('activeFilterBar');
  var lbl = document.getElementById('activeFilterLabel');
  if (parts.length) { bar.classList.add('show'); lbl.textContent = parts.join(' · '); }
  else { bar.classList.remove('show'); }
}

function applyFilters() {
  filtered = ALL_DATA.filter(function(r) {
    if (activeYear && (r.date_published || '').slice(0, 4) !== activeYear) return false;
    if (activeCategories.size > 0 && !activeCategories.has(r.source_category)) return false;
    if (activeSources.size > 0 && !activeSources.has(r.source_name)) return false;
    if (activeCountries.size > 0) {
      var cs = (r.country || '').split(',').map(function(s) { return s.trim(); });
      var ok2 = false; cs.forEach(function(c) { if (activeCountries.has(c)) ok2 = true; });
      if (!ok2) return false;
    }
    if (searchQuery) {
      var hay = [r.title, r.organisation, r.country, r.summary, r.source_name].join(' ').toLowerCase();
      if (hay.indexOf(searchQuery) === -1) return false;
    }
    return true;
  });
  updateFilterBar();
  render();
}

function render() {
  var sort = document.getElementById('sortSelect').value;
  var sorted = filtered.slice().sort(function(a, b) {
    if (sort === 'date_desc') return (b.date_published || '') > (a.date_published || '') ? 1 : -1;
    if (sort === 'date_asc')  return (a.date_published || '') > (b.date_published || '') ? 1 : -1;
    if (sort === 'title_asc') return (a.title || '').localeCompare(b.title || '');
    if (sort === 'org_asc')   return (a.organisation || '').localeCompare(b.organisation || '');
    return 0;
  });
  var totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = 1;
  var page = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  document.getElementById('resultCount').innerHTML =
    'Showing <strong>' + sorted.length + '</strong> of ' + ALL_DATA.length + ' use cases';

  if (sorted.length === 0) {
    document.getElementById('cards').innerHTML =
      '<div class="state-msg"><p>No results</p><p>Try adjusting your filters or search</p></div>';
    document.getElementById('pagination').innerHTML = '';
    return;
  }

  var html = '';
  page.forEach(function(r) {
    var date = (r.date_published || '—').slice(0, 7);
    var country1 = r.country ? r.country.split(',')[0].trim() : '';
    var titleInner = r.url
      ? '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">' + esc(r.title || 'Untitled') + '</a>'
      : esc(r.title || 'Untitled');
    var tagsHtml = '';
    if (country1) tagsHtml += '<span class="tag country">' + esc(country1) + '</span>';
    if (r.task_type)   tagsHtml += '<span class="tag task">'   + esc(fmtLabel(r.task_type))   + '</span>';
    if (r.effect_type) tagsHtml += '<span class="tag effect effect-' + esc(r.effect_type) + '">' + esc(fmtLabel(r.effect_type)) + '</span>';
    html += '<div class="card">' +
      '<div class="card-title">' + titleInner + '</div>' +
      '<div class="card-date">' + esc(date) + '</div>' +
      '<div class="card-meta">' +
        (r.organisation ? '<span class="card-org">' + esc(r.organisation) + '</span>' : '') +
        tagsHtml +
      '</div></div>';
  });
  document.getElementById('cards').innerHTML = html;

  var pages = [];
  if (totalPages > 1) {
    pages.push('<button class="page-btn" id="prevBtn"' + (currentPage === 1 ? ' disabled' : '') + '>← Prev</button>');
    for (var i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || Math.abs(i - currentPage) <= 2) {
        pages.push('<button class="page-btn' + (i === currentPage ? ' active' : '') + '" data-page="' + i + '">' + i + '</button>');
      } else if (Math.abs(i - currentPage) === 3) {
        pages.push('<span style="padding:8px 4px;color:var(--ash);font-family:var(--mono);font-size:10px">…</span>');
      }
    }
    pages.push('<button class="page-btn" id="nextBtn"' + (currentPage === totalPages ? ' disabled' : '') + '>Next →</button>');
  }
  var pag = document.getElementById('pagination');
  pag.innerHTML = pages.join('');
  pag.querySelectorAll('[data-page]').forEach(function(btn) {
    btn.addEventListener('click', function() { goPage(parseInt(btn.getAttribute('data-page'))); });
  });
  var prev = document.getElementById('prevBtn'), next = document.getElementById('nextBtn');
  if (prev) prev.addEventListener('click', function() { goPage(currentPage - 1); });
  if (next) next.addEventListener('click', function() { goPage(currentPage + 1); });
}

function goPage(p) { currentPage = p; render(); window.scrollTo({ top: 0, behavior: 'smooth' }); }

var TASK_COLORS = {
  'content_generation':                     '#b65536',
  'content_transformation':                 '#d4723c',
  'editing_and_optimisation':               '#d4a843',
  'discovery_and_monitoring':               '#5BB56A',
  'data_extraction_and_analysis':           '#3AADA8',
  'search_and_retrieval':                   '#4A8FCC',
  'transcription_and_translation':          '#6C6CC8',
  'verification_and_validation':            '#A66CC8',
  'audience_targeting_and_personalisation': '#D46AAE',
  'commercial_optimisation':                '#C85070',
  'moderation_and_interaction':             '#7CB87C',
};

var EFFECT_COLORS = {
  'efficiency':                '#b65536',
  'effectiveness_and_scaling': '#4A8FCC',
  'optimisation':              '#5BB56A',
};

function fmtLabel(s) {
  var r = s.replace(/_/g, ' ');
  return r.charAt(0).toUpperCase() + r.slice(1);
}

function buildCharts() {
  buildTimeline('taskTimeline',   'taskTimelineYears',   'taskTimelineBars',   'taskTimelineLegend',   STATS.task_by_year,   TASK_COLORS);
  buildTimeline('effectTimeline', 'effectTimelineYears', 'effectTimelineBars', 'effectTimelineLegend', STATS.effect_by_year, EFFECT_COLORS);
  buildBarChart('catChart', STATS.top_sources || [], 20);
  buildBarChart('countryChart', STATS.top_countries || [], 999);
  buildSourcesList();
  var yr = document.getElementById('insightsTotalYears');
  if (yr && STATS.by_year) yr.textContent = STATS.by_year.length;
}

function buildSourcesList() {
  var body = document.getElementById('sourcesTableBody');
  if (!body || !STATS.sources_list) return;
  var catCls = {'Academic':'src-cat-academic','Industry':'src-cat-industry','Curated':'src-cat-curated','Database':'src-cat-database'};
  body.innerHTML = STATS.sources_list.map(function(s) {
    return '<tr>' +
      '<td>' + esc(s.name) + '</td>' +
      '<td><span class="src-cat ' + (catCls[s.category] || '') + '">' + esc(s.category) + '</span></td>' +
      '<td class="src-count-cell">' + s.count + '</td>' +
      '</tr>';
  }).join('');
  var tot = document.getElementById('sourcesTotal');
  if (tot) tot.textContent = STATS.sources_list.length;
}

function buildTimeline(containerId, yearsId, barsId, legendId, data, colorMap) {
  if (!data || !data.years || !data.years.length) return;
  var years = data.years;
  var cats = Object.keys(data.categories);
  var colors = cats.map(function(c) { return colorMap[c] || '#c8bfad'; });
  var chartH = 220;

  var totals = years.map(function(_, yi) {
    return cats.reduce(function(s, c) { return s + (data.categories[c][yi] || 0); }, 0);
  });
  var maxTotal = Math.max.apply(null, totals);

  document.getElementById(yearsId).innerHTML = years.map(function(yr) {
    return '<div class="timeline-year-label">' + yr + '</div>';
  }).join('');

  var barsHtml = '';
  years.forEach(function(yr, yi) {
    var total = totals[yi];
    var segments = '';
    cats.forEach(function(c, ci) {
      var n = data.categories[c][yi] || 0;
      if (!n) return;
      var pct = (n / maxTotal * 100).toFixed(2);
      segments += '<div class="timeline-segment" data-pct="' + pct +
        '" style="height:0;background:' + colors[ci] + '"></div>';
    });
    var tipContent = yr + '|' + total + '|' + cats.map(function(c, ci) {
      return (data.categories[c][yi] || 0) + '|' + fmtLabel(c) + '|' + colors[ci];
    }).join('~');
    barsHtml += '<div class="timeline-bar-group" data-tip="' + tipContent + '">' + segments + '</div>';
  });

  var barsEl = document.getElementById(barsId);
  barsEl.innerHTML = barsHtml;

  var sharedTip = document.getElementById('sharedBarTooltip');
  if (!sharedTip) {
    sharedTip = document.createElement('div');
    sharedTip.id = 'sharedBarTooltip';
    sharedTip.className = 'bar-tooltip';
    document.body.appendChild(sharedTip);
  }

  barsEl.querySelectorAll('.timeline-bar-group').forEach(function(group) {
    group.addEventListener('mouseenter', function() {
      var parts = group.getAttribute('data-tip').split('|');
      var yr = parts[0], total = parts[1];
      var rows = parts.slice(2).join('|');
      var rowsHtml = rows.split('~').map(function(r) {
        var rp = r.split('|'); var n = parseInt(rp[0]);
        if (!n) return '';
        return '<div class="tooltip-row"><div class="tooltip-swatch" style="background:' + rp[2] + '"></div>' +
          '<span style="flex:1">' + rp[1] + '</span><strong>' + n + '</strong></div>';
      }).filter(Boolean).join('');
      sharedTip.innerHTML = '<div class="tooltip-year">' + yr + ' &middot; ' + total + ' cases</div>' + rowsHtml;
      sharedTip.style.display = 'block';
    });
    group.addEventListener('mouseleave', function() { sharedTip.style.display = 'none'; });
    group.addEventListener('mousemove', function(e) {
      var tipW = 210, tipH = sharedTip.offsetHeight, vw = window.innerWidth;
      var left = (e.clientX + tipW + 16 > vw) ? e.clientX - tipW - 8 : e.clientX + 14;
      sharedTip.style.left = left + 'px';
      sharedTip.style.top  = Math.max(8, e.clientY - tipH - 8) + 'px';
    });
  });

  document.getElementById(legendId).innerHTML = cats.map(function(c, ci) {
    return '<div class="legend-item"><div class="legend-dot" style="background:' + colors[ci] + '"></div>' + fmtLabel(c) + '</div>';
  }).join('');

  var animated = false;
  var container = document.getElementById(containerId);
  function animateBars() {
    if (animated) return; animated = true;
    barsEl.querySelectorAll('.timeline-bar-group').forEach(function(group, gi) {
      group.querySelectorAll('.timeline-segment').forEach(function(seg, si) {
        var pct = parseFloat(seg.getAttribute('data-pct'));
        var targetH = Math.round(pct / 100 * chartH);
        seg.style.transition = 'none'; seg.style.height = '0px';
        setTimeout(function() {
          seg.style.transition = 'height 0.7s cubic-bezier(0.22,1,0.36,1)';
          seg.style.height = targetH + 'px';
        }, gi * 60 + si * 20);
      });
    });
  }
  var tlObs = new IntersectionObserver(function(entries) {
    if (entries[0].isIntersecting) { animateBars(); tlObs.disconnect(); }
  }, { threshold: 0.15 });
  tlObs.observe(container);
  if (container.getBoundingClientRect().top < window.innerHeight) animateBars();
}

function buildBarChart(id, items, limit) {
  var container = document.getElementById(id);
  if (!container || !items.length) return;
  var top = items.slice(0, limit);
  var maxN = top[0][1];
  var html = top.map(function(item) {
    var label = item[0], count = item[1];
    return '<div class="bar-row"><span class="bar-label" title="' + esc(label) + '">' + esc(label) + '</span>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + (count/maxN*100).toFixed(1) + '%"></div></div>' +
      '<span class="bar-count">' + count + '</span></div>';
  }).join('');
  container.innerHTML = html;
  var barObs = new IntersectionObserver(function(entries) {
    entries.forEach(function(e) {
      if (e.isIntersecting) {
        e.target.querySelectorAll('.bar-fill').forEach(function(b) { b.classList.add('animated'); });
        barObs.unobserve(e.target);
      }
    });
  }, { threshold: 0.2 });
  barObs.observe(container);
}

function resetAll() {
  activeYear = null; activeCategories.clear(); activeSources.clear(); activeCountries.clear();
  searchQuery = ''; currentPage = 1;
  document.getElementById('searchInput').value = '';
  document.getElementById('sortSelect').value = 'date_desc';
  buildYearChart();
  buildFilters('categoryFilters', 'categories', activeCategories, toggleCategory);
  buildFilters('sourceFilters', 'sources', activeSources, toggleSource);
  buildFilters('countryFilters', 'countries', activeCountries, toggleCountry);
  applyFilters();
}

init();
</script>
</body>
</html>
"""


# ── spreadsheet.html template ──────────────────────────────────────────────────

SPREADSHEET_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Use Cases in News Organisations — Spreadsheet</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;1,400;1,600&family=Source+Sans+3:ital,wght@0,300;0,400;0,600;1,300&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --paper:   #f7f5f0;
  --ink:     #002147;
  --rust:    #b65536;
  --rust-lt: rgba(182,85,54,0.08);
  --ash:     #5c6577;
  --rule:    #dce2ea;
  --card:    #faf9f6;
  --mono:    'JetBrains Mono', monospace;
  --sans:    'Source Sans 3', sans-serif;
  --serif:   'Playfair Display', serif;
  --nav-h:   48px;
  --strip-h: 56px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; }
body { font-family: var(--sans); background: var(--paper); color: var(--ink); -webkit-font-smoothing: antialiased; display: flex; flex-direction: column; }

/* Nav */
nav {
  height: var(--nav-h); flex-shrink: 0;
  background: #002147;
  border-bottom: 1px solid rgba(255,255,255,0.12);
  padding: 0 32px; z-index: 20;
}
.nav-inner {
  max-width: 1280px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
  height: var(--nav-h);
}
.nav-brand {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.1em;
  text-transform: uppercase; color: white; text-decoration: none;
  display: flex; align-items: center; gap: 10px;
}
.brand-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--rust); animation: pulse 3s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity:0.6; transform:scale(1); } 50% { opacity:1; transform:scale(1.2); } }
.nav-links { display: flex; align-items: center; gap: 20px; }
.nav-link { font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: rgba(255,255,255,0.65); text-decoration: none; transition: color 0.15s; }
.nav-link:hover { color: white; }
.nav-link.active { color: white; }
.nav-meta { font-family: var(--mono); font-size: 10px; color: rgba(255,255,255,0.45); letter-spacing: 0.05em; }

/* Stats strip */
.stats-strip {
  height: var(--strip-h); flex-shrink: 0;
  background: var(--card); border-bottom: 1px solid var(--rule);
  display: flex; align-items: center; padding: 0 24px; gap: 0; overflow-x: auto;
}
.strip-title { font-family: var(--serif); font-size: 17px; font-style: italic; color: var(--ink); margin-right: 24px; white-space: nowrap; }
.stat-chips { display: flex; gap: 1px; flex-wrap: nowrap; }
.stat-chip { display: flex; align-items: center; gap: 6px; padding: 4px 14px; background: white; border: 1px solid var(--rule); border-radius: 2px; font-family: var(--mono); font-size: 10px; letter-spacing: 0.04em; color: var(--ash); white-space: nowrap; }
.stat-chip strong { font-size: 13px; color: var(--rust); font-weight: 500; }

/* App body */
.app-body { flex: 1; display: grid; grid-template-columns: 228px 1fr; overflow: hidden; min-height: 0; }

/* Sidebar */
.sidebar {
  background: var(--card); border-right: 1px solid var(--rule);
  overflow-y: auto; overflow-x: hidden; padding: 16px;
  display: flex; flex-direction: column; gap: 18px;
}
.sidebar::-webkit-scrollbar { width: 3px; }
.sidebar::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 2px; }
.sidebar-label { font-family: var(--mono); font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--ash); display: block; margin-bottom: 7px; }

.search-wrap { position: relative; }
.search-input { width: 100%; padding: 7px 10px 7px 30px; border: 1px solid var(--rule); border-radius: 2px; background: white; font-family: var(--sans); font-size: 12px; color: var(--ink); outline: none; }
.search-input:focus { border-color: var(--rust); }
.search-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--ash); font-size: 13px; pointer-events: none; }

.year-chart { display: flex; align-items: flex-end; gap: 3px; height: 48px; margin-top: 4px; }
.year-bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; cursor: pointer; }
.year-bar { width: 100%; background: var(--rule); border-radius: 2px 2px 0 0; transition: background 0.15s; min-height: 2px; }
.year-bar-wrap:hover .year-bar, .year-bar-wrap.active .year-bar { background: var(--rust); }
.year-label { font-family: var(--mono); font-size: 8px; color: var(--ash); transition: color 0.15s; }
.year-bar-wrap.active .year-label, .year-bar-wrap:hover .year-label { color: var(--rust); }

.pill-group { display: flex; flex-wrap: wrap; gap: 3px; }
.filter-pill { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 20px; border: 1px solid var(--rule); background: white; font-family: var(--mono); font-size: 9px; letter-spacing: 0.03em; color: var(--ash); cursor: pointer; transition: all 0.12s; word-break: break-word; }
.filter-pill:hover { border-color: var(--rust); color: var(--rust); background: var(--rust-lt); }
.filter-pill.active { background: var(--rust); border-color: var(--rust); color: white; }
.filter-pill .cnt { opacity: 0.6; font-size: 8px; }
.filter-pill.active .cnt { opacity: 0.8; }

.reset-btn { width: 100%; padding: 7px; border: 1px solid var(--rule); border-radius: 2px; background: none; font-family: var(--mono); font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ash); cursor: pointer; transition: all 0.12s; margin-top: auto; }
.reset-btn:hover { background: var(--rust); color: white; border-color: var(--rust); }

/* Table panel */
.table-panel { display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

.toolbar { flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; padding: 8px 16px; background: white; border-bottom: 1px solid var(--rule); gap: 12px; }
.result-count { font-family: var(--mono); font-size: 11px; color: var(--ash); white-space: nowrap; }
.result-count strong { color: var(--ink); font-size: 13px; }
.active-filter-tag { display: none; align-items: center; gap: 6px; background: var(--rust-lt); border: 1px solid rgba(182,85,54,0.2); border-radius: 20px; padding: 3px 10px; font-family: var(--mono); font-size: 9px; color: var(--rust); letter-spacing: 0.04em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.active-filter-tag.show { display: flex; }
.filter-clear { background: none; border: none; color: var(--rust); cursor: pointer; font-size: 13px; line-height: 1; padding: 0 0 0 2px; flex-shrink: 0; }

/* Scrollable table wrapper */
.table-wrap { flex: 1; overflow: auto; min-height: 0; }
.table-wrap::-webkit-scrollbar { width: 6px; height: 6px; }
.table-wrap::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 3px; }
.table-wrap::-webkit-scrollbar-corner { background: var(--card); }

/* Data table */
.data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; table-layout: fixed; }

.data-table thead th {
  position: sticky; top: 0;
  background: var(--card); border-bottom: 2px solid var(--rule);
  padding: 9px 12px; text-align: left;
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--ash); white-space: nowrap; cursor: pointer; user-select: none; z-index: 5;
}
.data-table thead th:hover { color: var(--rust); }
.data-table thead th.sorted-asc, .data-table thead th.sorted-desc { color: var(--rust); }
.sort-arrow { margin-left: 4px; opacity: 0.35; font-size: 10px; }
.sorted-asc .sort-arrow, .sorted-desc .sort-arrow { opacity: 1; }

.col-n    { width: 40px; }
.col-date { width: 74px; }
.col-title { width: auto; min-width: 200px; }
.col-org  { width: 155px; }
.col-ctry { width: 96px; }
.col-src    { width: 130px; }
.col-type   { width: 80px; }
.col-task   { width: 160px; }
.col-effect { width: 120px; }

.data-table tbody tr { border-bottom: 1px solid var(--rule); transition: background 0.08s; }
.data-table tbody tr:hover { background: var(--rust-lt); }
.data-table tbody tr:last-child { border-bottom: none; }
.data-table td { padding: 8px 12px; vertical-align: middle; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

td.col-n { font-family: var(--mono); font-size: 10px; color: var(--rule); text-align: right; padding-right: 8px; }
td.col-date { font-family: var(--mono); font-size: 11px; color: var(--ash); }
td.col-title { white-space: normal; line-height: 1.35; }
td.col-title a { color: var(--ink); text-decoration: none; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
td.col-title a:hover { color: var(--rust); text-decoration: underline; }
td.col-title span { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
td.col-org { font-size: 12px; color: var(--ash); }
td.col-ctry { font-family: var(--mono); font-size: 10px; }
td.col-task, td.col-effect { white-space: normal; overflow: visible; }
td.col-type { overflow: visible; }

.src-badge { display: inline-block; padding: 2px 7px; border-radius: 2px; font-family: var(--mono); font-size: 9px; letter-spacing: 0.03em; background: #e8f4ec; color: #236634; border: 1px solid #c3e0cb; white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.type-badge { display: inline-block; padding: 2px 7px; border-radius: 2px; font-family: var(--mono); font-size: 9px; letter-spacing: 0.03em; white-space: nowrap; }
.type-academic { background: #eef2fb; color: #1a4b9a; border: 1px solid #c5d4f0; }
.type-industry { background: #fdf3e8; color: #8a4a0a; border: 1px solid #f0d5b0; }
.type-curated  { background: #f2ebfb; color: #5b1fa8; border: 1px solid #d8c4f2; }
.type-database { background: var(--rust-lt); color: var(--rust); border: 1px solid rgba(182,85,54,0.2); }
.type-other    { background: var(--card); color: var(--ash); border: 1px solid var(--rule); }
.task-badge    { background: #f0eef8; color: #5b3ea6; border: 1px solid #c5bcec; white-space: normal; line-height: 1.3; }
.effect-badge             { background: #f0f4ff; color: #1a4b9a; border: 1px solid #c5d4f0; }
.effect-efficiency        { background: rgba(182,85,54,0.08); color: #b65536; border: 1px solid rgba(182,85,54,0.25); }
.effect-effectiveness     { background: #eef2fb; color: #1a4b9a; border: 1px solid #c5d4f0; }
.effect-optimisation      { background: #eaf5ed; color: #236634; border: 1px solid #c3e0cb; }

.empty-state { padding: 80px 24px; text-align: center; color: var(--ash); }
.empty-state p:first-child { font-family: var(--serif); font-size: 24px; color: var(--ink); font-style: italic; margin-bottom: 8px; }

@media (max-width: 860px) {
  html, body { overflow: auto; }
  .app-body { grid-template-columns: 1fr; }
  .sidebar { max-height: 240px; border-right: none; border-bottom: 1px solid var(--rule); }
  .strip-title { display: none; }
}
</style>
</head>
<body>

<nav>
  <div class="nav-inner">
    <a class="nav-brand" href="index.html">
      <span class="brand-dot"></span>
      AI in News Organisations
    </a>
    <div class="nav-links">
      <a class="nav-link" href="index.html">Overview</a>
      <a class="nav-link active" href="spreadsheet.html">Spreadsheet</a>
      <span class="nav-meta" id="generatedAt"></span>
    </div>
  </div>
</nav>

<div class="stats-strip">
  <span class="strip-title">All Use Cases</span>
  <div class="stat-chips" id="statChips">
    <div class="stat-chip"><strong>—</strong>&nbsp;loading</div>
  </div>
</div>

<div class="app-body">
  <aside class="sidebar">
    <div>
      <span class="sidebar-label">Search</span>
      <div class="search-wrap">
        <span class="search-icon">⌕</span>
        <input class="search-input" type="text" id="searchInput" placeholder="Title, organisation…">
      </div>
    </div>
    <div>
      <span class="sidebar-label">Year</span>
      <div class="year-chart" id="yearChart"></div>
    </div>
    <div>
      <span class="sidebar-label">Source</span>
      <div class="pill-group" id="sourceFilters"></div>
    </div>
    <div>
      <span class="sidebar-label">Country</span>
      <div class="pill-group" id="countryFilters"></div>
    </div>
    <div>
      <span class="sidebar-label">Type</span>
      <div class="pill-group" id="typeFilters"></div>
    </div>
    <button class="reset-btn" id="resetBtn">↺ Reset filters</button>
  </aside>

  <div class="table-panel">
    <div class="toolbar">
      <div class="result-count" id="resultCount">Loading…</div>
      <div class="active-filter-tag" id="activeFilterTag">
        <span id="activeFilterLabel"></span>
        <button class="filter-clear" id="filterClear" title="Clear all filters">✕</button>
      </div>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th class="col-n">#</th>
            <th class="col-date" data-col="date">Date <span class="sort-arrow">↕</span></th>
            <th class="col-title" data-col="title">Title <span class="sort-arrow">↕</span></th>
            <th class="col-org" data-col="org">Organisation <span class="sort-arrow">↕</span></th>
            <th class="col-ctry" data-col="country">Country <span class="sort-arrow">↕</span></th>
            <th class="col-src" data-col="source">Source <span class="sort-arrow">↕</span></th>
            <th class="col-type" data-col="type">Type <span class="sort-arrow">↕</span></th>
            <th class="col-task" data-col="task">Task <span class="sort-arrow">↕</span></th>
            <th class="col-effect" data-col="effect">Effect <span class="sort-arrow">↕</span></th>
          </tr>
        </thead>
        <tbody id="tableBody">
          <tr><td colspan="9"><div class="empty-state"><p>Loading…</p><p>Fetching use cases</p></div></td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
var ALL_DATA = [], STATS = {}, filtered = [];
var activeYear = null, activeSources = new Set(), activeCountries = new Set(), activeTypes = new Set();
var searchQuery = '', sortCol = 'date', sortDir = -1;

function esc(s) { var el = document.createElement('div'); el.textContent = String(s||''); return el.innerHTML; }
function fmtLabel(s) { var r=(s||'').replace(/_/g,' '); return r.charAt(0).toUpperCase()+r.slice(1); }

function init() {
  (function() {
    var p = __INLINE_DATA__;
    ALL_DATA = p.records; STATS = p.stats;
    var g = document.getElementById('generatedAt');
    if (g) g.textContent = 'Updated ' + p.generated_at;
    filtered = ALL_DATA.slice();
    buildStats();
    buildYearChart();
    buildFilters('sourceFilters',  'source',  activeSources,  toggleSource);
    buildFilters('countryFilters', 'country', activeCountries, toggleCountry);
    buildFilters('typeFilters',    'type',    activeTypes,     toggleType);
    applyFilters();
  })();
  document.getElementById('searchInput').addEventListener('input', function(e) { searchQuery = e.target.value.toLowerCase(); applyFilters(); });
  document.getElementById('resetBtn').addEventListener('click', resetAll);
  document.getElementById('filterClear').addEventListener('click', resetAll);
  document.querySelectorAll('thead th[data-col]').forEach(function(th) {
    th.addEventListener('click', function() {
      var col = th.getAttribute('data-col');
      if (sortCol === col) sortDir = -sortDir; else { sortCol = col; sortDir = col === 'date' ? -1 : 1; }
      updateSortHeaders(); render();
    });
  });
}

function buildStats() {
  var orgs={}, countries={}, sources={}, years={};
  ALL_DATA.forEach(function(d) {
    if (d.organisation) orgs[d.organisation]=true;
    if (d.source_name)  sources[d.source_name]=true;
    var yr=(d.date_published||'').slice(0,4); if(yr&&parseInt(yr)>2010) years[yr]=true;
    (d.country||'').split(',').forEach(function(c){c=c.trim();if(c)countries[c]=true;});
  });
  document.getElementById('statChips').innerHTML =
    chip(ALL_DATA.length,'use cases')+chip(Object.keys(orgs).length,'organisations')+
    chip(Object.keys(countries).length,'countries')+chip(Object.keys(sources).length,'sources')+
    chip(Object.keys(years).length,'years covered');
}
function chip(n,l){return '<div class="stat-chip"><strong>'+n+'</strong>&nbsp;'+l+'</div>';}

function buildYearChart() {
  var years=STATS.by_year||[]; if(!years.length)return;
  var maxN=0; years.forEach(function(y){if(y[1]>maxN)maxN=y[1];});
  var html='';
  years.forEach(function(item){
    var yr=item[0],n=item[1],h=Math.max(2,Math.round(n/maxN*44));
    var cls='year-bar-wrap'+(activeYear===yr?' active':'');
    html+='<div class="'+cls+'" data-year="'+yr+'" title="'+yr+': '+n+'">'+
          '<div class="year-bar" style="height:'+h+'px"></div>'+
          '<div class="year-label">'+yr.slice(2)+'</div></div>';
  });
  var c=document.getElementById('yearChart'); c.innerHTML=html;
  c.querySelectorAll('.year-bar-wrap').forEach(function(el){
    el.addEventListener('click',function(){
      activeYear=activeYear===el.getAttribute('data-year')?null:el.getAttribute('data-year');
      buildYearChart(); applyFilters();
    });
  });
}

function buildFilters(id,mode,activeSet,fn) {
  var counts={};
  ALL_DATA.forEach(function(r){
    var vals=mode==='source'?[r.source_name||'']:mode==='type'?[r.source_category||'']:(r.country||'').split(',').map(function(s){return s.trim();}).filter(Boolean);
    vals.forEach(function(v){if(v)counts[v]=(counts[v]||0)+1;});
  });
  var sorted=Object.keys(counts).map(function(k){return[k,counts[k]];}).sort(function(a,b){return b[1]-a[1];}).slice(0,20);
  var html='';
  sorted.forEach(function(item){
    var val=item[0],count=item[1];
    html+='<button class="filter-pill'+(activeSet.has(val)?' active':'')+'" data-val="'+esc(val)+'">'+esc(val)+' <span class="cnt">'+count+'</span></button>';
  });
  var c=document.getElementById(id); c.innerHTML=html;
  c.querySelectorAll('.filter-pill').forEach(function(btn){btn.addEventListener('click',function(){fn(btn.getAttribute('data-val'));});});
}
function toggleSource(v){toggle(v,activeSources);buildFilters('sourceFilters','source',activeSources,toggleSource);applyFilters();}
function toggleCountry(v){toggle(v,activeCountries);buildFilters('countryFilters','country',activeCountries,toggleCountry);applyFilters();}
function toggleType(v){toggle(v,activeTypes);buildFilters('typeFilters','type',activeTypes,toggleType);applyFilters();}
function toggle(v,set){if(set.has(v))set.delete(v);else set.add(v);}

function updateFilterTag() {
  var parts=[];
  if(activeYear)parts.push(activeYear);
  activeSources.forEach(function(v){parts.push(v);});
  activeCountries.forEach(function(v){parts.push(v);});
  activeTypes.forEach(function(v){parts.push(v);});
  if(searchQuery)parts.push('"'+searchQuery+'"');
  var tag=document.getElementById('activeFilterTag');
  var lbl=document.getElementById('activeFilterLabel');
  if(parts.length){tag.classList.add('show');lbl.textContent=parts.join(' · ');}
  else tag.classList.remove('show');
}

function applyFilters() {
  filtered=ALL_DATA.filter(function(r){
    if(activeYear&&(r.date_published||'').slice(0,4)!==activeYear)return false;
    if(activeSources.size>0&&!activeSources.has(r.source_name))return false;
    if(activeTypes.size>0&&!activeTypes.has(r.source_category))return false;
    if(activeCountries.size>0){
      var cs=(r.country||'').split(',').map(function(s){return s.trim();});
      var ok=false;cs.forEach(function(c){if(activeCountries.has(c))ok=true;});
      if(!ok)return false;
    }
    if(searchQuery){
      var hay=[r.title,r.organisation,r.country,r.source_name].join(' ').toLowerCase();
      if(hay.indexOf(searchQuery)===-1)return false;
    }
    return true;
  });
  updateFilterTag(); render();
}

function sortData(arr) {
  return arr.slice().sort(function(a,b){
    var va='',vb='';
    if(sortCol==='date'){va=a.date_published||'';vb=b.date_published||'';}
    else if(sortCol==='title'){va=(a.title||'').toLowerCase();vb=(b.title||'').toLowerCase();}
    else if(sortCol==='org'){va=(a.organisation||'').toLowerCase();vb=(b.organisation||'').toLowerCase();}
    else if(sortCol==='country'){va=(a.country||'').toLowerCase();vb=(b.country||'').toLowerCase();}
    else if(sortCol==='source'){va=(a.source_name||'').toLowerCase();vb=(b.source_name||'').toLowerCase();}
    else if(sortCol==='type'){va=(a.source_category||'').toLowerCase();vb=(b.source_category||'').toLowerCase();}
    else if(sortCol==='task'){va=(a.task_type||'').toLowerCase();vb=(b.task_type||'').toLowerCase();}
    else if(sortCol==='effect'){va=(a.effect_type||'').toLowerCase();vb=(b.effect_type||'').toLowerCase();}
    if(va<vb)return -sortDir; if(va>vb)return sortDir; return 0;
  });
}

function updateSortHeaders() {
  document.querySelectorAll('thead th[data-col]').forEach(function(th){
    th.classList.remove('sorted-asc','sorted-desc');
    var arrow=th.querySelector('.sort-arrow');
    if(th.getAttribute('data-col')===sortCol){
      th.classList.add(sortDir===1?'sorted-asc':'sorted-desc');
      if(arrow)arrow.textContent=sortDir===1?'↑':'↓';
    } else { if(arrow)arrow.textContent='↕'; }
  });
}

function render() {
  var rows=sortData(filtered);
  document.getElementById('resultCount').innerHTML='Showing <strong>'+rows.length+'</strong> of '+ALL_DATA.length+' use cases';
  if(!rows.length){
    document.getElementById('tableBody').innerHTML='<tr><td colspan="9"><div class="empty-state"><p>No results</p><p>Try adjusting your filters or search</p></div></td></tr>';
    return;
  }
  var tc={'Academic':'type-academic','Industry':'type-industry','Curated':'type-curated','Database':'type-database'};
  var ec={'efficiency':'effect-efficiency','effectiveness_and_scaling':'effect-effectiveness','optimisation':'effect-optimisation'};
  var html='';
  rows.forEach(function(r,i){
    var date=(r.date_published||'—').slice(0,7);
    var country=r.country?r.country.split(',')[0].trim():'—';
    var cls=tc[r.source_category]||'type-other';
    var ecls=ec[r.effect_type]||'';
    var titleEl=r.url?'<a href="'+esc(r.url)+'" target="_blank" rel="noopener">'+esc(r.title||'Untitled')+'</a>':'<span>'+esc(r.title||'Untitled')+'</span>';
    html+='<tr>'+
      '<td class="col-n">'+(i+1)+'</td>'+
      '<td class="col-date">'+esc(date)+'</td>'+
      '<td class="col-title">'+titleEl+'</td>'+
      '<td class="col-org">'+esc(r.organisation||'—')+'</td>'+
      '<td class="col-ctry">'+esc(country)+'</td>'+
      '<td class="col-src"><span class="src-badge">'+esc(r.source_name||'—')+'</span></td>'+
      '<td class="col-type"><span class="type-badge '+cls+'">'+esc(r.source_category||'—')+'</span></td>'+
      '<td class="col-task">'+(r.task_type?'<span class="type-badge task-badge">'+esc(fmtLabel(r.task_type))+'</span>':'—')+'</td>'+
      '<td class="col-effect">'+(r.effect_type?'<span class="type-badge effect-badge '+ecls+'">'+esc(fmtLabel(r.effect_type))+'</span>':'—')+'</td>'+
      '</tr>';
  });
  document.getElementById('tableBody').innerHTML=html;
}

function resetAll() {
  activeYear=null;activeSources.clear();activeCountries.clear();activeTypes.clear();
  searchQuery='';sortCol='date';sortDir=-1;
  document.getElementById('searchInput').value='';
  buildYearChart();
  buildFilters('sourceFilters','source',activeSources,toggleSource);
  buildFilters('countryFilters','country',activeCountries,toggleCountry);
  buildFilters('typeFilters','type',activeTypes,toggleType);
  updateSortHeaders(); applyFilters();
}

init();
</script>
</body>
</html>
"""


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate index.html + spreadsheet.html + data.json from the use cases database")
    parser.add_argument("--db",      default=str(DB_PATH),  help="Path to SQLite database")
    parser.add_argument("--out-dir", default=str(ROOT_DIR), help="Output directory (default: project root)")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        print("Error: database not found at", db_path)
        print("Run some scrapers first to populate the database.")
        sys.exit(1)

    print("Reading database:", db_path)
    data, stats = load_data(db_path)
    print(" ", stats["total"], "records loaded")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = {"generated_at": generated_at, "records": data, "stats": stats}
    inline_json = json.dumps(payload, ensure_ascii=False)

    # data.json kept for http serving
    data_path = out_dir / "data.json"
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Data written:        ", data_path, f"({data_path.stat().st_size // 1024} KB)")

    # inline json so file:// opens work without a server
    html_path = out_dir / "index.html"
    html_path.write_text(HTML.replace("__INLINE_DATA__", inline_json), encoding="utf-8")
    print("Dashboard written:   ", html_path)

    # spreadsheet.html
    sheet_path = out_dir / "spreadsheet.html"
    sheet_path.write_text(SPREADSHEET_HTML.replace("__INLINE_DATA__", inline_json), encoding="utf-8")
    print("Spreadsheet written: ", sheet_path)

    print()
    print("Next steps:")
    print("  git add index.html spreadsheet.html data.json")
    print("  git commit -m 'Refresh dashboard'")
    print("  git push")


if __name__ == "__main__":
    main()
