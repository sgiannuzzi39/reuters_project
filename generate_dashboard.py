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
               task_type, effect_type, gatekeeping_stage
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
    by_gate_stage  = {}
    source_detail  = {}

    for r in data:
        yr = (r["date_published"] or "")[:4]
        if yr and yr.isdigit() and 2008 <= int(yr) <= 2030:
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
        gs = (r["gatekeeping_stage"] or "").strip()
        if gs:
            by_gate_stage[gs] = by_gate_stage.get(gs, 0) + 1

    def _build_timeline(data, field, names):
        year_buckets = {}
        for r in data:
            yr = (r["date_published"] or "")[:4]
            if not yr or not yr.isdigit() or int(yr) < 2008 or int(yr) > 2026:
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

    SOURCE_URLS = {
        "arXiv":                                "https://arxiv.org/search/",
        "Columbia Journalism Review":           "https://www.cjr.org",
        "Digiday":                              "https://digiday.com",
        "Editor & Publisher":                   "https://www.editorandpublisher.com",
        "Generative AI Newsroom":               "https://generative-ai-newsroom.com",
        "Google News Initiative":               "https://newsinitiative.withgoogle.com/resources/stories/",
        "INMA":                                 "https://www.inma.org",
        "Journalism.co.uk":                     "https://www.journalism.co.uk",
        "JournalismAI":                         "https://www.journalismai.info/resources/case-studies",
        "Nieman Lab":                           "https://www.niemanlab.org",
        "Poynter":                              "https://www.poynter.org",
        "Press Gazette":                        "https://pressgazette.co.uk",
        "Reuters Institute":                    "https://reutersinstitute.politics.ox.ac.uk",
        "Reuters Institute Digital News Report 2025": "https://www.digitalnewsreport.org/",
        "WAN-IFRA":                             "https://wan-ifra.org",
        "WAN-IFRA Age of AI in the Newsroom":   "https://womeninnews.org/wp-content/uploads/2025/05/The-Age-of-AI-in-the-newsroom-Report_EN.pdf",
    }

    task_names   = [t for t, _ in sorted(by_task_type.items(),   key=lambda x: -x[1])]
    effect_names = [e for e, _ in sorted(by_effect_type.items(), key=lambda x: -x[1])]
    gate_names   = [g for g, _ in sorted(by_gate_stage.items(),  key=lambda x: -x[1])]

    stats = {
        "total":          len(data),
        "by_year":        sorted(by_year.items()),
        "top_countries":  sorted(by_country.items(),  key=lambda x: -x[1]),
        "top_categories": sorted(by_category.items(), key=lambda x: -x[1])[:12],
        "top_sources":    sorted(by_source.items(),   key=lambda x: -x[1])[:15],
        "source_names":   sorted(by_source.keys()),
        "sources_list":   sorted(
            [{"name": k, "category": v["category"], "count": v["count"],
              "url": SOURCE_URLS.get(k, "")}
             for k, v in source_detail.items()],
            key=lambda x: -x["count"]
        ),
        "task_by_year":   _build_timeline(data, "task_type",        task_names),
        "effect_by_year": _build_timeline(data, "effect_type",       effect_names),
        "gate_by_year":   _build_timeline(data, "gatekeeping_stage", gate_names),
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
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500;1,600;1,700&display=swap" rel="stylesheet">
<style>
:root {
  --paper:   #f7f8fa;
  --ink:     #232331;
  --accent:  #12285f;
  --rust:    #12285f;
  --rust-lt: rgba(18,40,95,0.07);
  --ash:     #676f7a;
  --rule:    #e5e5e5;
  --card:    #ffffff;
  --sans:    'Playfair Display', sans-serif;
  --green:   #2a8d46;
  --blue:    #0074bd;
  --amber:   #b07a00;
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


.inst-attr {
  font-family: var(--sans); font-size: 13px; font-weight: 500; letter-spacing: 0.03em;
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
.nav-brand { text-decoration: none; display: flex; align-items: center; }
.nav-logo { height: 38px; display: block; }
.nav-meta { font-family: var(--sans); font-size: 10px; color: rgba(255,255,255,0.45); letter-spacing: 0.05em; }
.nav-links { display: flex; align-items: center; gap: 20px; }
.nav-link {
  font-family: var(--sans); font-size: 10px; letter-spacing: 0.04em;
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
  font-family: var(--sans); font-size: 11px; letter-spacing: 0.05em;
  text-transform: uppercase; color: var(--rust); margin-bottom: 20px;
  display: flex; align-items: center; gap: 10px;
}
.hero h1 {
  font-family: var(--sans); font-size: clamp(40px, 6vw, 72px);
  font-weight: 500; line-height: 1.08; letter-spacing: -0.02em;
  color: var(--ink); margin-bottom: 20px;
}
.hero h1 em { font-style: normal; color: var(--rust); }
.hero-sub {
  font-size: 18px; color: var(--ash);
  line-height: 1.72; max-width: 540px; margin-bottom: 32px; font-weight: 300;
}

.figure-note {
  margin-top: 16px; padding: 14px 18px;
  background: var(--card); border-left: 3px solid var(--rule);
  font-size: 15px; color: var(--ash); line-height: 1.68;
}
.figure-note strong { color: var(--ink); font-weight: 600; }
.figure-note p { margin: 0 0 8px; }
.figure-note p:last-child { margin-bottom: 0; }

.methods-section { border-top: 1px solid var(--rule); padding: 64px 32px 80px; }
.methods-inner { max-width: 1280px; margin: 0 auto; }
.methods-body { max-width: 780px; margin-top: 24px; }
.methods-body p { font-size: 16px; color: var(--ash); line-height: 1.82; margin-bottom: 18px; }
.methods-body p:last-child { margin-bottom: 0; }
.methods-body strong { color: var(--ink); font-weight: 600; }

.sources-section { border-top: 1px solid var(--rule); padding: 64px 32px 80px; background: var(--card); }
.sources-inner { max-width: 1280px; margin: 0 auto; }
.sources-table { width: 100%; border-collapse: collapse; margin-top: 24px; }
.sources-table th { text-align: left; padding: 8px 16px; font-family: var(--sans); font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ash); border-bottom: 2px solid var(--rule); }
.sources-table td { padding: 11px 16px; font-size: 14px; color: var(--ink); border-bottom: 1px solid var(--rule); vertical-align: middle; }
.sources-table tr:last-child td { border-bottom: none; }
.src-count-cell { font-family: var(--sans); font-size: 12px; color: var(--ash); text-align: right; }
.src-cat { display: inline-block; padding: 2px 8px; border-radius: 2px; font-family: var(--sans); font-size: 10px; letter-spacing: 0.04em; }
.src-cat-academic { background: #eef2fb; color: #1a4b9a; border: 1px solid #c5d4f0; }
.src-cat-industry  { background: #fdf3e8; color: #8a4a0a; border: 1px solid #f0d5b0; }
.src-cat-curated   { background: #f2ebfb; color: #5b1fa8; border: 1px solid #d8c4f2; }
.src-cat-database  { background: var(--rust-lt); color: var(--rust); border: 1px solid rgba(18,40,95,0.15); }

.stats-band { border-bottom: 1px solid rgba(255,255,255,0.08); background: #002147; }
.stats-inner {
  max-width: 1280px; margin: 0 auto; padding: 0 32px;
  display: grid; grid-template-columns: repeat(5, 1fr);
}
.stat-cell { padding: 32px 24px; text-align: left; border-right: 1px solid rgba(255,255,255,0.08); }
.stat-cell:last-child { border-right: none; }
.stat-num {
  font-family: var(--sans); font-size: 52px; font-weight: 300; line-height: 1;
  letter-spacing: -0.02em; color: white; display: block; margin-bottom: 6px;
}
.stat-label {
  font-family: var(--sans); font-size: 12px; letter-spacing: 0.06em;
  text-transform: uppercase; color: rgba(255,255,255,0.45);
}


.insights-section { border-top: 1px solid var(--rule); background: var(--card); padding: 64px 32px 80px; }
.insights-inner { max-width: 1280px; margin: 0 auto; }
.insights-header { margin-bottom: 48px; }
.insights-title { font-family: var(--sans); font-size: clamp(26px, 3vw, 38px); font-weight: 500; line-height: 1.1; margin-bottom: 14px; margin-top: 12px; letter-spacing: -0.01em; }
.insights-sub { font-size: 17px; color: var(--ash); max-width: 600px; line-height: 1.68; }

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
.timeline-year-label { flex: 1; font-family: var(--sans); font-size: 11px; letter-spacing: 0.04em; color: var(--ash); text-align: center; min-width: 60px; }
.timeline-bars { display: flex; gap: 6px; align-items: flex-end; height: 220px; border-bottom: 1px solid var(--rule); margin-bottom: 20px; min-width: 540px; }
.timeline-bar-group { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: stretch; min-width: 60px; cursor: pointer; position: relative; height: 100%; }
.timeline-segment { width: 100%; flex-shrink: 0; }
.timeline-bar-group:hover .timeline-segment { opacity: 0.85; }
.bar-tooltip {
  display: none; position: fixed;
  background: var(--ink); color: white; border-radius: var(--radius);
  padding: 10px 14px; width: 190px; z-index: 9000;
  font-family: var(--sans); font-size: 9px; line-height: 1.8; letter-spacing: 0.03em;
  pointer-events: none; box-shadow: 0 4px 16px rgba(0,0,0,0.25);
}
.tooltip-year { font-size: 11px; font-weight: 500; margin-bottom: 4px; opacity: 0.7; }
.tooltip-row { display: flex; justify-content: space-between; gap: 8px; }
.tooltip-swatch { width: 8px; height: 8px; border-radius: 1px; flex-shrink: 0; margin-top: 2px; }
.timeline-legend { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-family: var(--sans); font-size: 11px; letter-spacing: 0.03em; color: var(--ash); text-transform: uppercase; }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }

.annotation-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 48px; }
.annotation-card {
  background: white; border: 1px solid var(--rule); border-radius: var(--radius);
  padding: 20px; position: relative; overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.annotation-card:hover { border-color: var(--ash); }
.annotation-year { font-family: var(--sans); font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--rust); margin-bottom: 6px; }
.annotation-label { font-family: var(--sans); font-size: 16px; font-style: italic; color: var(--ink); margin-bottom: 10px; }
.annotation-text { font-size: 12px; color: var(--ash); line-height: 1.6; }

.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
.chart-panel { background: white; border: 1px solid var(--rule); border-radius: var(--radius); padding: 24px; }
.chart-panel-label { font-family: var(--sans); font-size: 15px; font-weight: 600; color: var(--ink); margin-bottom: 20px; }
.chart-panel-scroll { max-height: 520px; overflow-y: auto; padding-right: 4px; }
.chart-panel-scroll::-webkit-scrollbar { width: 3px; }
.chart-panel-scroll::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 2px; }
.bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.bar-label { font-size: 13px; color: var(--ink); width: 200px; min-width: 200px; max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; height: 16px; background: var(--rule); border-radius: 2px; overflow: hidden; min-width: 60px; }
.bar-fill { height: 100%; border-radius: 2px; background: var(--rust); transform-origin: left; transform: scaleX(0); transition: transform 1s cubic-bezier(0.22,1,0.36,1); }
.bar-fill.animated { transform: scaleX(1); }
.bar-count { font-family: var(--sans); font-size: 12px; color: var(--ash); min-width: 30px; text-align: right; }

footer { border-top: 1px solid var(--rule); padding: 32px; font-family: var(--sans); font-size: 12px; color: var(--ash); text-align: center; letter-spacing: 0.04em; }
.footer-inner { max-width: 1280px; margin: 0 auto; }

@media (max-width: 900px) {
  .stats-inner { grid-template-columns: repeat(3, 1fr); }
  .stat-cell:nth-child(3) { border-right: none; }
  .stat-cell:nth-child(4) { border-right: 1px solid rgba(255,255,255,0.08); }
  .annotation-grid { grid-template-columns: 1fr 1fr; }
  .chart-grid { grid-template-columns: 1fr; }
  .insights-section { padding: 48px 24px 64px; }
  .hero { padding: 48px 24px 40px; }
  nav { padding: 0 24px; }
}
@media (max-width: 560px) {
  .stats-inner { grid-template-columns: 1fr 1fr; }
  .stat-cell:nth-child(2) { border-right: none; }
  .stat-cell:nth-child(4) { border-right: none; }
  .annotation-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<nav>
  <div class="nav-inner">
    <a class="nav-brand" href="#">
      <img src="images/logo.png" alt="Reuters Institute · University of Oxford" class="nav-logo">
    </a>
    <div class="nav-links">
      <a class="nav-link active" href="index.html">Overview</a>
      <a class="nav-link" href="sources.html">Sources</a>
      <a class="nav-link" href="spreadsheet.html">Spreadsheet</a>
      <span class="nav-meta" id="generatedAt"></span>
    </div>
  </div>
</nav>

<section class="hero">
  <p class="inst-attr"><a href="https://reutersinstitute.politics.ox.ac.uk" target="_blank" rel="noopener">Reuters Institute for the Study of Journalism</a> · University of Oxford</p>
  <h1>AI Use Cases in<br><em>News Organisations</em></h1>
  <p class="hero-sub">A dataset of publicly documented AI use cases in news organisations worldwide, drawn from industry publications, research databases, and curated reports.</p>
</section>

<div class="stats-band">
  <div class="stats-inner" id="statsRow">
    <div class="stat-cell"><span class="stat-num">—</span><span class="stat-label">Loading</span></div>
  </div>
</div>


<section class="insights-section">
  <div class="insights-inner">
    <div class="insights-header">
      <div class="hero-eyebrow">Insights</div>
      <h2 class="insights-title">How AI adoption has evolved</h2>
      <p class="insights-sub">Distribution of AI use cases across <span id="insightsTotalYears"></span> years of documented cases, broken down by functional task type, primary effect delivered, and stage in the news production process.</p>
    </div>

    <div class="timeline-block">
      <div class="timeline-block-label">What AI is doing, by task type</div>
      <div class="timeline-chart" id="taskTimeline">
        <div class="timeline-years" id="taskTimelineYears"></div>
        <div class="timeline-bars" id="taskTimelineBars"></div>
        <div class="timeline-legend" id="taskTimelineLegend"></div>
      </div>
      <div class="figure-note">
        <p><strong>Content generation</strong>: AI writes or produces original text, audio, or video content, including automated articles and data-driven reports.</p>
        <p><strong>Content transformation</strong>: AI reformats, summarises, or adapts existing content for a different platform, language, or audience.</p>
        <p><strong>Editing &amp; optimisation</strong>: AI reviews or improves content for style, clarity, SEO, or engagement before publication.</p>
        <p><strong>Discovery &amp; monitoring</strong>: AI tracks topics, sources, or events to surface relevant information for journalists or editors.</p>
        <p><strong>Data extraction &amp; analysis</strong>: AI processes structured or unstructured data to extract facts, trends, or patterns for reporting.</p>
        <p><strong>Search &amp; retrieval</strong>: AI enables search across large archives, databases, or documents to surface relevant material.</p>
        <p><strong>Transcription &amp; translation</strong>: AI converts speech to text, or translates content between languages, to support production or access.</p>
        <p><strong>Verification &amp; validation</strong>: AI checks facts, detects misinformation, or assesses the credibility of claims and sources.</p>
        <p><strong>Audience targeting &amp; personalisation</strong>: AI tailors content, recommendations, or delivery to individual users based on behaviour or preferences.</p>
        <p><strong>Commercial optimisation</strong>: AI supports advertising, subscription, or revenue operations through targeting, pricing, or prediction.</p>
        <p><strong>Moderation &amp; interaction</strong>: AI manages audience comments, detects harmful content, or powers conversational interfaces for readers.</p>
      </div>
    </div>

    <div class="timeline-block">
      <div class="timeline-block-label">What AI is delivering, by effect type</div>
      <div class="timeline-chart" id="effectTimeline">
        <div class="timeline-years" id="effectTimelineYears"></div>
        <div class="timeline-bars" id="effectTimelineBars"></div>
        <div class="timeline-legend" id="effectTimelineLegend"></div>
      </div>
      <div class="figure-note">
        <p><strong>Efficiency</strong>: AI reduces time, cost, or effort for tasks that were previously done manually.</p>
        <p><strong>Effectiveness &amp; scaling</strong>: AI enables tasks or volumes not previously possible, or dramatically expands what a team can produce.</p>
        <p><strong>Optimisation</strong>: AI improves quality, targeting, personalisation, or distribution without fundamentally changing the underlying task.</p>
      </div>
    </div>

    <div class="timeline-block">
      <div class="timeline-block-label">Where in the newsroom, by gatekeeping stage</div>
      <div class="timeline-chart" id="gateTimeline">
        <div class="timeline-years" id="gateTimelineYears"></div>
        <div class="timeline-bars" id="gateTimelineBars"></div>
        <div class="timeline-legend" id="gateTimelineLegend"></div>
      </div>
      <div class="figure-note">
        <p><strong>Access &amp; observation</strong>: AI discovers, collects, or monitors information before it enters production. Includes trend detection, news monitoring, lead generation, and audience analytics for story ideas.</p>
        <p><strong>Selection &amp; filtering</strong>: AI evaluates, verifies, or organises information during editorial vetting. Includes fact-checking, claim verification, transcription of source material, and document analysis.</p>
        <p><strong>Processing &amp; editing</strong>: AI produces or refines news content. Includes automated writing, reformatting, summarisation, copy-editing, headline generation, and SEO optimisation.</p>
        <p><strong>Publishing &amp; distribution</strong>: AI delivers content or manages audience interaction after publication. Includes personalisation, recommendation systems, comment moderation, and chatbot interfaces.</p>
      </div>
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

function esc(s) {
  var el = document.createElement('div');
  el.textContent = String(s || '');
  return el.innerHTML;
}

function init() {
  var payload = __INLINE_DATA__;
  ALL_DATA = payload.records;
  STATS = payload.stats;
  var g = document.getElementById('generatedAt');
  if (g) g.textContent = 'Updated ' + payload.generated_at;
  buildStats();
  buildCharts();
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
  return '<div class="stat-cell"><span class="stat-num">' + n +
    '</span><span class="stat-label">' + label + '</span></div>';
}


var TASK_COLORS = {
  'content_generation':                     '#12285f',
  'content_transformation':                 '#d4408a',
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
  'efficiency':                '#12285f',
  'effectiveness_and_scaling': '#4A8FCC',
  'optimisation':              '#5BB56A',
};

var GATE_COLORS = {
  'processing_and_editing':      '#d4a843',
  'publishing_and_distribution': '#3AADA8',
  'access_and_observation':      '#12285f',
  'selection_and_filtering':     '#5BB56A',
};

function fmtLabel(s) {
  var r = s.replace(/_/g, ' ');
  return r.charAt(0).toUpperCase() + r.slice(1);
}

function buildCharts() {
  buildTimeline('taskTimeline',   'taskTimelineYears',   'taskTimelineBars',   'taskTimelineLegend',   STATS.task_by_year,   TASK_COLORS);
  buildTimeline('effectTimeline', 'effectTimelineYears', 'effectTimelineBars', 'effectTimelineLegend', STATS.effect_by_year, EFFECT_COLORS);
  buildTimeline('gateTimeline',   'gateTimelineYears',   'gateTimelineBars',   'gateTimelineLegend',   STATS.gate_by_year,   GATE_COLORS);
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
<title>AI Use Cases in News Organisations: Spreadsheet</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500;1,600;1,700&display=swap" rel="stylesheet">
<style>
:root {
  --paper:   #f7f8fa;
  --ink:     #232331;
  --accent:  #12285f;
  --rust:    #12285f;
  --rust-lt: rgba(18,40,95,0.07);
  --ash:     #676f7a;
  --rule:    #e5e5e5;
  --card:    #ffffff;
  --sans:    'Playfair Display', sans-serif;
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
.nav-brand { text-decoration: none; display: flex; align-items: center; }
.nav-logo { height: 38px; display: block; }
.nav-links { display: flex; align-items: center; gap: 20px; }
.nav-link { font-family: var(--sans); font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; color: rgba(255,255,255,0.65); text-decoration: none; transition: color 0.15s; }
.nav-link:hover { color: white; }
.nav-link.active { color: white; }
.nav-meta { font-family: var(--sans); font-size: 10px; color: rgba(255,255,255,0.45); letter-spacing: 0.05em; }

/* Stats strip */
.stats-strip {
  height: var(--strip-h); flex-shrink: 0;
  background: var(--card); border-bottom: 1px solid var(--rule);
  display: flex; align-items: center; padding: 0 24px; gap: 0; overflow-x: auto;
}
.strip-title { font-family: var(--sans); font-size: 17px; font-style: italic; color: var(--ink); margin-right: 24px; white-space: nowrap; }
.stat-chips { display: flex; gap: 1px; flex-wrap: nowrap; }
.stat-chip { display: flex; align-items: center; gap: 6px; padding: 4px 14px; background: white; border: 1px solid var(--rule); border-radius: 2px; font-family: var(--sans); font-size: 10px; letter-spacing: 0.04em; color: var(--ash); white-space: nowrap; }
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
.sidebar-label { font-family: var(--sans); font-size: 9px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ash); display: block; margin-bottom: 7px; }

.search-wrap { position: relative; }
.search-input { width: 100%; padding: 7px 10px 7px 30px; border: 1px solid var(--rule); border-radius: 2px; background: white; font-family: var(--sans); font-size: 12px; color: var(--ink); outline: none; }
.search-input:focus { border-color: var(--rust); }
.search-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--ash); font-size: 13px; pointer-events: none; }

.year-chart { display: flex; align-items: flex-end; gap: 3px; height: 48px; margin-top: 4px; }
.year-bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; cursor: pointer; }
.year-bar { width: 100%; background: var(--rule); border-radius: 2px 2px 0 0; transition: background 0.15s; min-height: 2px; }
.year-bar-wrap:hover .year-bar, .year-bar-wrap.active .year-bar { background: var(--rust); }
.year-label { font-family: var(--sans); font-size: 8px; color: var(--ash); transition: color 0.15s; }
.year-bar-wrap.active .year-label, .year-bar-wrap:hover .year-label { color: var(--rust); }

.pill-group { display: flex; flex-direction: column; }
.filter-pill { display: flex; align-items: center; justify-content: space-between; padding: 3px 0 3px 8px; border: none; border-left: 2px solid transparent; border-radius: 0; background: none; font-family: var(--sans); font-size: 11px; color: var(--ash); cursor: pointer; text-align: left; width: 100%; transition: color 0.12s, border-left-color 0.12s; }
.filter-pill:hover { color: var(--ink); border-left-color: var(--rule); background: none; }
.filter-pill.active { color: var(--accent); border-left-color: var(--accent); font-weight: 500; background: none; }
.filter-pill .cnt { font-family: var(--sans); font-size: 9px; color: var(--ash); opacity: 0.6; flex-shrink: 0; }
.filter-pill.active .cnt { opacity: 0.8; color: var(--accent); }

.reset-btn { width: 100%; padding: 7px; border: 1px solid var(--rule); border-radius: 2px; background: none; font-family: var(--sans); font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ash); cursor: pointer; transition: all 0.12s; margin-top: auto; }
.reset-btn:hover { background: var(--rust); color: white; border-color: var(--rust); }

/* Table panel */
.table-panel { display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

.toolbar { flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; padding: 8px 16px; background: white; border-bottom: 1px solid var(--rule); gap: 12px; }
.result-count { font-family: var(--sans); font-size: 11px; color: var(--ash); white-space: nowrap; }
.result-count strong { color: var(--ink); font-size: 13px; }
.active-filter-tag { display: none; align-items: center; gap: 6px; background: var(--rust-lt); border: 1px solid rgba(18,40,95,0.15); border-radius: 20px; padding: 3px 10px; font-family: var(--sans); font-size: 9px; color: var(--rust); letter-spacing: 0.04em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
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
  font-family: var(--sans); font-size: 9px; letter-spacing: 0.05em; text-transform: uppercase;
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
.col-effect { width: 110px; }
.col-gate   { width: 150px; }

.data-table tbody tr { border-bottom: 1px solid var(--rule); transition: background 0.08s; }
.data-table tbody tr:hover { background: var(--rust-lt); }
.data-table tbody tr:last-child { border-bottom: none; }
.data-table td { padding: 8px 12px; vertical-align: middle; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

td.col-n { font-family: var(--sans); font-size: 10px; color: var(--rule); text-align: right; padding-right: 8px; }
td.col-date { font-family: var(--sans); font-size: 11px; color: var(--ash); }
td.col-title { white-space: normal; line-height: 1.35; }
td.col-title a { color: var(--ink); text-decoration: none; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
td.col-title a:hover { color: var(--rust); text-decoration: underline; }
td.col-title span { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
td.col-org { font-size: 12px; color: var(--ash); }
td.col-ctry { font-family: var(--sans); font-size: 10px; }
td.col-type, td.col-task, td.col-effect, td.col-gate { white-space: normal; overflow: hidden; vertical-align: top; }

.src-badge { display: inline-block; padding: 2px 7px; border-radius: 2px; font-family: var(--sans); font-size: 9px; letter-spacing: 0.03em; background: #e8f4ec; color: #236634; border: 1px solid #c3e0cb; white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.type-badge { display: inline-block; padding: 2px 7px; border-radius: 2px; font-family: var(--sans); font-size: 9px; letter-spacing: 0.03em; white-space: nowrap; }
.type-academic { background: #eef2fb; color: #1a4b9a; border: 1px solid #c5d4f0; }
.type-industry { background: #fdf3e8; color: #8a4a0a; border: 1px solid #f0d5b0; }
.type-curated  { background: #f2ebfb; color: #5b1fa8; border: 1px solid #d8c4f2; }
.type-database { background: var(--rust-lt); color: var(--rust); border: 1px solid rgba(18,40,95,0.15); }
.type-other    { background: var(--card); color: var(--ash); border: 1px solid var(--rule); }
.task-badge    { background: #f0eef8; color: #5b3ea6; border: 1px solid #c5bcec; white-space: normal; line-height: 1.3; }
.effect-badge             { background: #f0f4ff; color: #1a4b9a; border: 1px solid #c5d4f0; }
.effect-efficiency        { background: rgba(18,40,95,0.07); color: #12285f; border: 1px solid rgba(18,40,95,0.2); }
.effect-effectiveness     { background: #eef2fb; color: #1a4b9a; border: 1px solid #c5d4f0; }
.effect-optimisation      { background: #eaf5ed; color: #236634; border: 1px solid #c3e0cb; }
.gate-badge               { white-space: normal; line-height: 1.3; }
.gate-access              { background: rgba(18,40,95,0.07); color: #12285f; border: 1px solid rgba(18,40,95,0.2); }
.gate-selection           { background: #eaf5ed; color: #236634; border: 1px solid #c3e0cb; }
.gate-processing          { background: #fdf7e8; color: #7a4e0a; border: 1px solid #f0d5a0; }
.gate-publishing          { background: #e8f8f7; color: #1a6b68; border: 1px solid #b0dedd; }

.empty-state { padding: 80px 24px; text-align: center; color: var(--ash); }
.empty-state p:first-child { font-family: var(--sans); font-size: 24px; color: var(--ink); font-style: italic; margin-bottom: 8px; }

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
      <img src="images/logo.png" alt="Reuters Institute · University of Oxford" class="nav-logo">
    </a>
    <div class="nav-links">
      <a class="nav-link" href="index.html">Overview</a>
      <a class="nav-link" href="sources.html">Sources</a>
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
      <span class="sidebar-label">Task type</span>
      <div class="pill-group" id="taskFilters"></div>
    </div>
    <div>
      <span class="sidebar-label">Effect type</span>
      <div class="pill-group" id="effectFilters"></div>
    </div>
    <div>
      <span class="sidebar-label">Gatekeeping stage</span>
      <div class="pill-group" id="gateFilters"></div>
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
            <th class="col-gate" data-col="gate">Stage <span class="sort-arrow">↕</span></th>
          </tr>
        </thead>
        <tbody id="tableBody">
          <tr><td colspan="10"><div class="empty-state"><p>Loading…</p><p>Fetching use cases</p></div></td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
var ALL_DATA = [], STATS = {}, filtered = [];
var activeYear = null, activeSources = new Set(), activeTasks = new Set(), activeEffects = new Set(), activeGates = new Set();
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
    buildFilters('sourceFilters', 'source', activeSources, toggleSource);
    buildFilters('taskFilters',   'task',   activeTasks,   toggleTask);
    buildFilters('effectFilters', 'effect', activeEffects, toggleEffect);
    buildFilters('gateFilters',   'gate',   activeGates,   toggleGate);
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
    var vals=mode==='source'?[r.source_name||'']:mode==='task'?[r.task_type||'']:mode==='effect'?[r.effect_type||'']:mode==='gate'?[r.gatekeeping_stage||'']:[];
    vals.forEach(function(v){if(v)counts[v]=(counts[v]||0)+1;});
  });
  var sorted=Object.keys(counts).map(function(k){return[k,counts[k]];}).sort(function(a,b){return b[1]-a[1];}).slice(0,20);
  var html='';
  sorted.forEach(function(item){
    var val=item[0],count=item[1];
    var label=mode==='source'?val:fmtLabel(val);
    html+='<button class="filter-pill'+(activeSet.has(val)?' active':'')+'" data-val="'+esc(val)+'">'+esc(label)+' <span class="cnt">'+count+'</span></button>';
  });
  var c=document.getElementById(id); c.innerHTML=html;
  c.querySelectorAll('.filter-pill').forEach(function(btn){btn.addEventListener('click',function(){fn(btn.getAttribute('data-val'));});});
}
function toggleSource(v){toggle(v,activeSources);buildFilters('sourceFilters','source',activeSources,toggleSource);applyFilters();}
function toggleTask(v){toggle(v,activeTasks);buildFilters('taskFilters','task',activeTasks,toggleTask);applyFilters();}
function toggleEffect(v){toggle(v,activeEffects);buildFilters('effectFilters','effect',activeEffects,toggleEffect);applyFilters();}
function toggleGate(v){toggle(v,activeGates);buildFilters('gateFilters','gate',activeGates,toggleGate);applyFilters();}
function toggle(v,set){if(set.has(v))set.delete(v);else set.add(v);}

function updateFilterTag() {
  var parts=[];
  if(activeYear)parts.push(activeYear);
  activeSources.forEach(function(v){parts.push(v);});
  activeTasks.forEach(function(v){parts.push(fmtLabel(v));});
  activeEffects.forEach(function(v){parts.push(fmtLabel(v));});
  activeGates.forEach(function(v){parts.push(fmtLabel(v));});
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
    if(activeTasks.size>0&&!activeTasks.has(r.task_type))return false;
    if(activeEffects.size>0&&!activeEffects.has(r.effect_type))return false;
    if(activeGates.size>0&&!activeGates.has(r.gatekeeping_stage))return false;
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
    else if(sortCol==='gate'){va=(a.gatekeeping_stage||'').toLowerCase();vb=(b.gatekeeping_stage||'').toLowerCase();}
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
    document.getElementById('tableBody').innerHTML='<tr><td colspan="10"><div class="empty-state"><p>No results</p><p>Try adjusting your filters or search</p></div></td></tr>';
    return;
  }
  var tc={'Academic':'type-academic','Industry':'type-industry','Curated':'type-curated','Database':'type-database'};
  var ec={'efficiency':'effect-efficiency','effectiveness_and_scaling':'effect-effectiveness','optimisation':'effect-optimisation'};
  var gc={'access_and_observation':'gate-access','selection_and_filtering':'gate-selection','processing_and_editing':'gate-processing','publishing_and_distribution':'gate-publishing'};
  var html='';
  rows.forEach(function(r,i){
    var date=(r.date_published||'—').slice(0,7);
    var country=r.country?r.country.split(',')[0].trim():'—';
    var cls=tc[r.source_category]||'type-other';
    var ecls=ec[r.effect_type]||'';
    var gcls=gc[r.gatekeeping_stage]||'';
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
      '<td class="col-gate">'+(r.gatekeeping_stage?'<span class="type-badge gate-badge '+gcls+'">'+esc(fmtLabel(r.gatekeeping_stage))+'</span>':'—')+'</td>'+
      '</tr>';
  });
  document.getElementById('tableBody').innerHTML=html;
}

function resetAll() {
  activeYear=null;activeSources.clear();activeTasks.clear();activeEffects.clear();activeGates.clear();
  searchQuery='';sortCol='date';sortDir=-1;
  document.getElementById('searchInput').value='';
  buildYearChart();
  buildFilters('sourceFilters','source',activeSources,toggleSource);
  buildFilters('taskFilters','task',activeTasks,toggleTask);
  buildFilters('effectFilters','effect',activeEffects,toggleEffect);
  buildFilters('gateFilters','gate',activeGates,toggleGate);
  updateSortHeaders(); applyFilters();
}

init();
</script>
</body>
</html>
"""


# ── sources.html template ──────────────────────────────────────────────────────

SOURCES_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sources: AI Use Cases in News Organisations</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500;1,600;1,700&display=swap" rel="stylesheet">
<style>
:root {
  --paper:   #f7f8fa;
  --ink:     #232331;
  --accent:  #12285f;
  --rust:    #12285f;
  --rust-lt: rgba(18,40,95,0.07);
  --ash:     #676f7a;
  --rule:    #e5e5e5;
  --card:    #ffffff;
  --sans:    'Playfair Display', sans-serif;
  --green:   #2a8d46;
  --blue:    #0074bd;
  --amber:   #b07a00;
  --radius:  2px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { font-family: var(--sans); background: var(--paper); color: var(--ink); min-height: 100vh; -webkit-font-smoothing: antialiased; }

nav {
  position: sticky; top: 0; z-index: 100;
  background: #002147; border-bottom: 1px solid rgba(255,255,255,0.12); padding: 0 32px;
}
.nav-inner { max-width: 1280px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; height: 48px; }
.nav-brand { text-decoration: none; display: flex; align-items: center; }
.nav-logo { height: 38px; display: block; }
.nav-meta { font-family: var(--sans); font-size: 10px; color: rgba(255,255,255,0.45); letter-spacing: 0.05em; }
.nav-links { display: flex; align-items: center; gap: 20px; }
.nav-link { font-family: var(--sans); font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; color: rgba(255,255,255,0.65); text-decoration: none; transition: color 0.15s; }
.nav-link:hover { color: white; }
.nav-link.active { color: white; }

.page-header { background: #002147; padding: 72px 32px 56px; }
.page-header .hero-eyebrow { color: rgba(255,255,255,0.45); margin-bottom: 16px; }
.page-title { font-family: var(--sans); font-size: clamp(36px, 5vw, 64px); font-weight: 500; line-height: 1.05; letter-spacing: -0.02em; color: white; margin-bottom: 16px; }
.page-sub { font-size: 16px; color: rgba(255,255,255,0.55); line-height: 1.7; max-width: 560px; font-weight: 400; margin-bottom: 40px; }
.header-stats { display: flex; gap: 0; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 32px; }
.header-stat { padding-right: 40px; margin-right: 40px; border-right: 1px solid rgba(255,255,255,0.1); }
.header-stat:last-child { border-right: none; }
.header-stat-num { font-family: var(--sans); font-size: 36px; font-weight: 300; color: white; line-height: 1; letter-spacing: -0.02em; display: block; margin-bottom: 4px; }
.header-stat-label { font-family: var(--sans); font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; color: rgba(255,255,255,0.4); }

.sources-section { padding: 64px 32px 80px; background: var(--card); }
.sources-inner { max-width: 1280px; margin: 0 auto; }
.section-title { font-family: var(--sans); font-size: clamp(22px, 2.5vw, 32px); font-weight: 500; letter-spacing: -0.01em; margin-bottom: 8px; }
.section-sub { font-size: 15px; color: var(--ash); line-height: 1.6; margin-bottom: 32px; }
.sources-table { width: 100%; border-collapse: collapse; }
.sources-table th { text-align: left; padding: 8px 16px; font-family: var(--sans); font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ash); border-bottom: 2px solid var(--rule); }
.sources-table td { padding: 11px 16px; font-size: 14px; color: var(--ink); border-bottom: 1px solid var(--rule); vertical-align: middle; }
.sources-table tr:last-child td { border-bottom: none; }
.src-count-cell { font-family: var(--sans); font-size: 13px; font-weight: 500; color: var(--ink); text-align: right; width: 48px; }
.src-bar-cell { width: 180px; padding: 11px 16px; }
.src-bar-wrap { height: 4px; background: var(--rule); border-radius: 2px; overflow: hidden; }
.src-bar-fill { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.8s cubic-bezier(0.22,1,0.36,1); }
.src-link { color: var(--ink); text-decoration: none; border-bottom: 1px solid var(--rule); transition: color 0.15s, border-color 0.15s; }
.src-link:hover { color: var(--rust); border-color: var(--rust); }
.src-group-header td { font-family: var(--sans); font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ash); padding: 24px 16px 6px; background: var(--paper); font-weight: 500; border-bottom: 1px solid var(--rule); }
.src-group-header:first-child td { padding-top: 8px; }

.methods-section { border-bottom: 1px solid var(--rule); padding: 64px 32px 80px; }
.methods-inner { max-width: 1280px; margin: 0 auto; }
.methods-body { max-width: 780px; margin-top: 24px; }
.methods-body p { font-size: 16px; color: var(--ash); line-height: 1.82; margin-bottom: 18px; }
.methods-body p:last-child { margin-bottom: 0; }
.methods-body strong { color: var(--ink); font-weight: 600; }

.geo-section { border-top: 1px solid var(--rule); padding: 64px 32px 80px; background: var(--paper); }
.geo-inner { max-width: 1280px; margin: 0 auto; }
.chart-panel { background: white; border: 1px solid var(--rule); border-radius: var(--radius); padding: 24px; margin-top: 32px; }
.chart-panel-scroll { max-height: 560px; overflow-y: auto; padding-right: 4px; }
.chart-panel-scroll::-webkit-scrollbar { width: 3px; }
.chart-panel-scroll::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 2px; }
.bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.bar-label { font-size: 13px; color: var(--ink); width: 200px; min-width: 200px; max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; height: 16px; background: var(--rule); border-radius: 2px; overflow: hidden; min-width: 60px; }
.bar-fill { height: 100%; border-radius: 2px; background: var(--rust); transform-origin: left; transform: scaleX(0); transition: transform 1s cubic-bezier(0.22,1,0.36,1); }
.bar-fill.animated { transform: scaleX(1); }
.bar-count { font-family: var(--sans); font-size: 12px; color: var(--ash); min-width: 30px; text-align: right; }

footer { border-top: 1px solid var(--rule); padding: 32px; font-family: var(--sans); font-size: 12px; color: var(--ash); text-align: center; letter-spacing: 0.04em; }
.footer-inner { max-width: 1280px; margin: 0 auto; }

.hero-eyebrow { font-family: var(--sans); font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; color: var(--rust); margin-bottom: 20px; }

@media (max-width: 900px) {
  .page-header { padding: 48px 24px 40px; }
  .sources-section, .geo-section { padding: 48px 24px 64px; }
  .header-stats { flex-wrap: wrap; gap: 20px; }
  .header-stat { border-right: none; padding-right: 0; margin-right: 0; }
  nav { padding: 0 24px; }
}
</style>
</head>
<body>

<nav>
  <div class="nav-inner">
    <a class="nav-brand" href="index.html">
      <img src="images/logo.png" alt="Reuters Institute · University of Oxford" class="nav-logo">
    </a>
    <div class="nav-links">
      <a class="nav-link" href="index.html">Overview</a>
      <a class="nav-link active" href="sources.html">Sources</a>
      <a class="nav-link" href="spreadsheet.html">Spreadsheet</a>
      <span class="nav-meta" id="generatedAt"></span>
    </div>
  </div>
</nav>

<header class="page-header">
  <div class="page-header-inner" style="max-width:1280px;margin:0 auto">
    <div class="hero-eyebrow">Sources &amp; Coverage</div>
    <h1 class="page-title">Data sources</h1>
    <p class="page-sub">Spanning industry reporting, curated databases, and academic and practitioner research. Records go back to 2008.</p>
  </div>
</header>

<section class="methods-section">
  <div class="methods-inner">
    <div>
      <div class="hero-eyebrow">Methodology</div>
      <h2 class="section-title">How this dataset was built</h2>
    </div>
    <div class="methods-body">
      <p>This dataset was compiled by systematically scraping and analysing publicly available reporting on AI adoption in news organisations from 16 industry, research, and curated sources. Each record represents a documented AI use case, or a specific deployment or application of AI technology by an identifiable news organisation.</p>
      <p>Use cases were identified through automated scraping of source websites, then filtered using a language model (GPT-4o-mini) to exclude articles that did not describe a concrete AI application by a news organisation. Cases were then automatically classified by functional task type (what the AI does) and primary effect type (what benefit it delivers), with uncertain classifications flagged for low confidence.</p>
      <p><strong>Important limitations.</strong> This dataset captures only what has been publicly documented, majoritively in English, across a specific set of monitored sources. Many deployments go unreported, while high-profile organisations attract disproportionate coverage. Documentation standards and terminology vary significantly across outlets, regions, and time periods. The dataset should be read as a partial and illustrative snapshot of documented AI adoption as opposed to a definitive map of the field.</p>
    </div>
  </div>
</section>

<section class="sources-section">
  <div class="sources-inner">
    <h2 class="section-title">Sources &amp; records</h2>
    <p class="section-sub">All <span id="sourcesTotal"></span> sources drawn on to compile the dataset, with record counts.</p>
    <table class="sources-table">
      <thead>
        <tr>
          <th>Source</th>
          <th></th>
          <th style="text-align:right">Records</th>
        </tr>
      </thead>
      <tbody id="sourcesTableBody"></tbody>
    </table>
  </div>
</section>

<section class="geo-section">
  <div class="geo-inner">
    <h2 class="section-title">Geographic distribution</h2>
    <p class="section-sub">Countries represented across all <span id="geoTotal"></span> documented use cases.</p>
    <div class="chart-panel">
      <div class="chart-panel-scroll"><div id="countryChart"></div></div>
    </div>
  </div>
</section>

<footer>
  <div class="footer-inner">
    Reuters Institute for the Study of Journalism · University of Oxford · <em>AI Use Cases in News Organisations</em>
  </div>
</footer>

<script>
var STATS = {};

function esc(s) { var el = document.createElement('div'); el.textContent = String(s||''); return el.innerHTML; }

function init() {
  var payload = __INLINE_DATA__;
  STATS = payload.stats;
  var g = document.getElementById('generatedAt');
  if (g) g.textContent = 'Updated ' + payload.generated_at;
  buildSourcesList();
  buildBarChart('countryChart', STATS.top_countries || [], 999);
  var gt = document.getElementById('geoTotal');
  if (gt) gt.textContent = payload.records ? payload.records.length : '';
  // header stats
  var countries = {};
  (payload.records || []).forEach(function(r) {
    (r.country||'').split(',').forEach(function(c){c=c.trim();if(c)countries[c]=true;});
  });
  var el;
  el = document.getElementById('statTotal');    if (el) el.textContent = payload.records ? payload.records.length : '—';
  el = document.getElementById('statSources');  if (el) el.textContent = STATS.sources_list ? STATS.sources_list.length : '—';
  el = document.getElementById('statCountries');if (el) el.textContent = Object.keys(countries).length || '—';
}

function buildSourcesList() {
  var body = document.getElementById('sourcesTableBody');
  if (!body || !STATS.sources_list) return;
  var maxCount = STATS.sources_list.reduce(function(m, s) { return Math.max(m, s.count); }, 0);
  var catOrder = ['Industry', 'Curated', 'Academic', 'Database'];
  var grouped = {};
  STATS.sources_list.forEach(function(s) {
    var cat = s.category || 'Other';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(s);
  });
  var html = '';
  var allCats = catOrder.filter(function(c) { return grouped[c] && grouped[c].length; });
  Object.keys(grouped).forEach(function(c) { if (catOrder.indexOf(c) === -1) allCats.push(c); });
  allCats.forEach(function(cat) {
    html += '<tr class="src-group-header"><td colspan="3">' + esc(cat) + '</td></tr>';
    grouped[cat].forEach(function(s) {
      var nameEl = s.url
        ? '<a class="src-link" href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.name) + '</a>'
        : esc(s.name);
      var pct = maxCount > 0 ? (s.count / maxCount * 100).toFixed(1) : 0;
      html += '<tr>' +
        '<td>' + nameEl + '</td>' +
        '<td class="src-bar-cell"><div class="src-bar-wrap"><div class="src-bar-fill" style="width:' + pct + '%"></div></div></td>' +
        '<td class="src-count-cell">' + s.count + '</td>' +
        '</tr>';
    });
  });
  body.innerHTML = html;
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

    # sources.html
    src_path = out_dir / "sources.html"
    src_path.write_text(SOURCES_HTML.replace("__INLINE_DATA__", inline_json), encoding="utf-8")
    print("Sources written:     ", src_path)

    print()
    print("Next steps:")
    print("  git add index.html sources.html spreadsheet.html data.json")
    print("  git commit -m 'Refresh dashboard'")
    print("  git push")


if __name__ == "__main__":
    main()
