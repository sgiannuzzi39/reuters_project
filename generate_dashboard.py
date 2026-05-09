"""
generate_dashboard.py
---------------------
Reads the live SQLite database and generates a self-contained dashboard.html
with all data embedded. Run this any time after adding new scraped data.

Usage:
    python generate_dashboard.py
    python generate_dashboard.py --output my_dashboard.html
    python generate_dashboard.py --db data/usecases.db --output dashboard.html
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scrapers"))
from scraper_base import get_db, DB_PATH

ROOT_DIR = Path(__file__).resolve().parent


# ── Data extraction ────────────────────────────────────────────────────────────

def load_data(db_path: Path) -> tuple[list[dict], dict]:
    conn = get_db(db_path)

    records = conn.execute("""
        SELECT id, title, organisation, country, date_published,
               source_name, source_category, summary, url
        FROM use_cases
        WHERE source_name != 'Test'
        ORDER BY date_published DESC
    """).fetchall()
    data = [dict(r) for r in records]

    # Compute stats for charts
    by_year     = {}
    by_country  = {}
    by_category = {}

    for r in data:
        yr = (r["date_published"] or "")[:4]
        if yr and yr.isdigit() and 2015 <= int(yr) <= 2030:
            by_year[yr] = by_year.get(yr, 0) + 1

        for c in (r["country"] or "").split(","):
            c = c.strip()
            if c and c != "Global":
                by_country[c] = by_country.get(c, 0) + 1

        for cat in (r["summary"] or "").split(","):
            cat = cat.strip()
            if cat:
                by_category[cat] = by_category.get(cat, 0) + 1

    stats = {
        "total":          len(data),
        "by_year":        sorted(by_year.items()),
        "top_countries":  sorted(by_country.items(),  key=lambda x: -x[1])[:15],
        "top_categories": sorted(by_category.items(), key=lambda x: -x[1])[:12],
    }

    conn.close()
    return data, stats


# ── HTML template ──────────────────────────────────────────────────────────────

def build_html(data: list[dict], stats: dict, generated_at: str) -> str:
    data_json  = json.dumps(data,  ensure_ascii=False)
    stats_json = json.dumps(stats, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI in the Newsroom — Dataset Explorer</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:      #1a1a1a;
    --paper:    #f5f0e8;
    --cream:    #ede8dc;
    --rule:     #c8bfad;
    --accent:   #c0392b;
    --accent2:  #2c5f8a;
    --muted:    #7a7060;
    --card-bg:  #ffffff;
    --tag-bg:   #e8e2d6;
  }}

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'DM Sans', sans-serif;
    background: var(--paper);
    color: var(--ink);
    min-height: 100vh;
  }}

  /* ── Masthead ── */
  .masthead {{
    background: var(--ink);
    color: var(--paper);
    padding: 40px 48px 32px;
    border-bottom: 3px solid var(--accent);
  }}
  .masthead-label {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--rule);
    margin-bottom: 12px;
  }}
  .masthead h1 {{
    font-family: 'DM Serif Display', serif;
    font-size: clamp(28px, 4vw, 48px);
    line-height: 1.1;
    font-weight: 400;
  }}
  .masthead h1 em {{ font-style: italic; color: #c8bfad; }}
  .masthead-meta {{
    margin-top: 16px;
    font-size: 12px;
    color: var(--rule);
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .masthead-meta .dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent); display: inline-block; margin-right: 6px;
  }}
  .generated {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: #555;
    margin-left: auto;
  }}

  /* ── Stats row ── */
  .stats-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 1px;
    background: var(--rule);
    border-bottom: 1px solid var(--rule);
  }}
  .stat-cell {{
    background: var(--cream);
    padding: 20px 24px;
    text-align: center;
  }}
  .stat-num {{
    font-family: 'DM Serif Display', serif;
    font-size: 36px;
    color: var(--accent);
    line-height: 1;
  }}
  .stat-label {{
    font-size: 10px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted);
    margin-top: 4px;
  }}

  /* ── Layout ── */
  .layout {{
    display: grid;
    grid-template-columns: 280px 1fr;
    min-height: calc(100vh - 220px);
  }}

  /* ── Sidebar ── */
  .sidebar {{
    background: var(--cream);
    border-right: 1px solid var(--rule);
    overflow-y: auto;
    position: sticky;
    top: 0;
    max-height: calc(100vh - 220px);
  }}
  .sidebar-section {{
    padding: 18px 18px 14px;
    border-bottom: 1px solid var(--rule);
  }}
  .sidebar-title {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 10px;
  }}

  /* Search */
  .search-wrap {{ position: relative; }}
  .search-wrap input {{
    width: 100%;
    padding: 8px 10px 8px 32px;
    border: 1px solid var(--rule);
    background: white;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    color: var(--ink);
    border-radius: 2px;
    outline: none;
  }}
  .search-wrap input:focus {{ border-color: var(--accent2); }}
  .search-icon {{
    position: absolute; left: 10px; top: 50%;
    transform: translateY(-50%);
    color: var(--muted); font-size: 13px;
  }}

  /* Year chart */
  .year-chart {{
    display: flex; align-items: flex-end;
    gap: 3px; height: 52px; margin-top: 8px;
  }}
  .year-bar-wrap {{
    flex: 1; display: flex; flex-direction: column;
    align-items: center; gap: 3px; cursor: pointer;
  }}
  .year-bar {{
    width: 100%; background: var(--rule);
    border-radius: 1px 1px 0 0;
    transition: background 0.15s;
    min-height: 2px;
  }}
  .year-bar-wrap:hover .year-bar,
  .year-bar-wrap.active .year-bar {{ background: var(--accent); }}
  .year-label {{
    font-size: 8px; color: var(--muted);
    font-family: 'DM Mono', monospace;
  }}

  /* Filter buttons */
  .filter-btn {{
    display: flex; width: 100%;
    padding: 5px 8px;
    background: none; border: none;
    text-align: left; cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    font-size: 12px; color: var(--ink);
    border-radius: 2px;
    justify-content: space-between; align-items: center;
    transition: background 0.12s;
  }}
  .filter-btn:hover {{ background: var(--tag-bg); }}
  .filter-btn.active {{ background: var(--ink); color: white; }}
  .filter-btn.active .filter-count {{ background: var(--accent); color: white; }}
  .filter-count {{
    font-family: 'DM Mono', monospace;
    font-size: 10px; background: var(--tag-bg);
    padding: 1px 6px; border-radius: 10px; color: var(--muted);
    flex-shrink: 0; margin-left: 6px;
  }}

  /* Reset */
  .reset-btn {{
    width: 100%; padding: 8px;
    background: none; border: 1px solid var(--rule);
    font-family: 'DM Mono', monospace;
    font-size: 10px; letter-spacing: 1px;
    text-transform: uppercase; color: var(--muted);
    cursor: pointer; border-radius: 2px;
    transition: all 0.15s;
  }}
  .reset-btn:hover {{ background: var(--accent); color: white; border-color: var(--accent); }}

  /* ── Main ── */
  .main {{ overflow-y: auto; }}

  .toolbar {{
    padding: 10px 24px;
    border-bottom: 1px solid var(--rule);
    display: flex; justify-content: space-between; align-items: center;
    background: white; position: sticky; top: 0; z-index: 10;
  }}
  .result-count {{
    font-family: 'DM Mono', monospace;
    font-size: 11px; color: var(--muted);
  }}
  .result-count strong {{ color: var(--ink); font-size: 14px; }}
  .sort-select {{
    font-family: 'DM Sans', sans-serif;
    font-size: 12px; border: 1px solid var(--rule);
    padding: 5px 8px; background: white; color: var(--ink); cursor: pointer;
  }}

  /* Cards */
  .cards {{
    padding: 12px 20px;
    display: flex; flex-direction: column; gap: 1px;
  }}
  .card {{
    background: white; border: 1px solid var(--rule);
    padding: 14px 18px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 6px 14px; align-items: start;
    transition: border-color 0.15s, box-shadow 0.15s;
  }}
  .card:hover {{
    border-color: var(--accent2);
    box-shadow: 2px 2px 0 var(--accent2);
  }}
  .card-title {{
    font-family: 'DM Serif Display', serif;
    font-size: 15px; font-weight: 400;
    line-height: 1.3; color: var(--ink);
  }}
  .card-title a {{ color: inherit; text-decoration: none; }}
  .card-title a:hover {{ color: var(--accent2); }}
  .card-date {{
    grid-column: 2; grid-row: 1;
    font-family: 'DM Mono', monospace;
    font-size: 11px; color: var(--muted);
    white-space: nowrap; text-align: right;
  }}
  .card-meta {{
    font-size: 11px; color: var(--muted);
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    grid-column: 1 / -1;
  }}
  .tag {{
    display: inline-block; padding: 2px 7px;
    background: var(--tag-bg); border-radius: 2px;
    font-size: 10px; font-family: 'DM Mono', monospace;
    color: var(--muted); letter-spacing: 0.3px;
  }}
  .tag.source {{ background: #dce8f0; color: #2c5f8a; }}
  .tag.country {{ background: #f0e8dc; color: #8a5c2c; }}

  .no-results {{
    padding: 60px 24px; text-align: center; color: var(--muted);
  }}
  .no-results p:first-child {{
    font-family: 'DM Serif Display', serif;
    font-size: 24px; margin-bottom: 8px;
  }}

  /* Pagination */
  .pagination {{
    padding: 20px 24px;
    display: flex; justify-content: center; gap: 4px;
  }}
  .page-btn {{
    padding: 6px 12px;
    border: 1px solid var(--rule); background: white;
    font-family: 'DM Mono', monospace; font-size: 11px;
    cursor: pointer; border-radius: 2px; color: var(--ink);
    transition: all 0.15s;
  }}
  .page-btn:hover {{ background: var(--ink); color: white; border-color: var(--ink); }}
  .page-btn.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
  .page-btn:disabled {{ opacity: 0.3; cursor: not-allowed; }}

  @media (max-width: 768px) {{
    .layout {{ grid-template-columns: 1fr; }}
    .sidebar {{ position: static; max-height: none; border-right: none; border-bottom: 1px solid var(--rule); }}
    .masthead {{ padding: 24px; }}
    .generated {{ display: none; }}
  }}
</style>
</head>
<body>

<div class="masthead">
  <div class="masthead-label">Oxford Dissertation Research · AI in Journalism</div>
  <h1>AI Adoption in News Organisations<br><em>Dataset Explorer</em></h1>
  <div class="masthead-meta">
    <span><span class="dot"></span>JournalismAI Case Studies</span>
    <span><span class="dot"></span>ONA AI in the Newsroom</span>
    <span><span class="dot"></span>Reuters Institute DNR 2025</span>
    <span class="generated">Generated {generated_at}</span>
  </div>
</div>

<div class="stats-row" id="statsRow"></div>

<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-title">Search</div>
      <div class="search-wrap">
        <span class="search-icon">⌕</span>
        <input type="text" id="searchInput" placeholder="Organisation, keyword…">
      </div>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-title">Year</div>
      <div class="year-chart" id="yearChart"></div>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-title">Category</div>
      <div id="categoryFilters"></div>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-title">Source</div>
      <div id="sourceFilters"></div>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-title">Country</div>
      <div id="countryFilters"></div>
    </div>

    <div class="sidebar-section">
      <button class="reset-btn" onclick="resetAll()">↺ Reset all filters</button>
    </div>
  </aside>

  <main class="main">
    <div class="toolbar">
      <div class="result-count" id="resultCount">Loading…</div>
      <select class="sort-select" id="sortSelect" onchange="render()">
        <option value="date_desc">Date: newest first</option>
        <option value="date_asc">Date: oldest first</option>
        <option value="title_asc">Title A–Z</option>
        <option value="org_asc">Organisation A–Z</option>
      </select>
    </div>
    <div class="cards" id="cards"></div>
    <div class="pagination" id="pagination"></div>
  </main>
</div>

<script>
const ALL_DATA = {data_json};
const STATS    = {stats_json};

let filtered        = [...ALL_DATA];
let currentPage     = 1;
const PAGE_SIZE     = 30;
let activeYear      = null;
let activeCategories = new Set();
let activeSources   = new Set();
let activeCountries = new Set();
let searchQuery     = '';

// ── Stats ──────────────────────────────────────────────────────────────────
function buildStats() {{
  const orgs = new Set(ALL_DATA.map(d => d.organisation)).size;
  const countries = new Set(
    ALL_DATA.flatMap(d => (d.country || '').split(',').map(c => c.trim())).filter(Boolean)
  ).size;
  const sources = new Set(ALL_DATA.map(d => d.source_name)).size;
  const years = new Set(
    ALL_DATA.map(d => (d.date_published || '').slice(0,4)).filter(y => y && parseInt(y) > 2010)
  ).size;

  document.getElementById('statsRow').innerHTML = `
    <div class="stat-cell"><div class="stat-num">${{ALL_DATA.length}}</div><div class="stat-label">Use Cases</div></div>
    <div class="stat-cell"><div class="stat-num">${{orgs}}</div><div class="stat-label">Organisations</div></div>
    <div class="stat-cell"><div class="stat-num">${{countries}}</div><div class="stat-label">Countries</div></div>
    <div class="stat-cell"><div class="stat-num">${{sources}}</div><div class="stat-label">Sources</div></div>
    <div class="stat-cell"><div class="stat-num">${{years}}</div><div class="stat-label">Years Covered</div></div>
  `;
}}

// ── Year chart ─────────────────────────────────────────────────────────────
function buildYearChart() {{
  const maxCount = Math.max(...STATS.by_year.map(([,n]) => n));
  document.getElementById('yearChart').innerHTML = STATS.by_year.map(([yr, n]) => `
    <div class="year-bar-wrap ${{activeYear === yr ? 'active' : ''}}"
         onclick="toggleYear('${{yr}}')" title="${{yr}}: ${{n}} cases">
      <div class="year-bar" style="height:${{Math.max(4, Math.round(n / maxCount * 46))}}px"></div>
      <div class="year-label">${{yr.slice(2)}}</div>
    </div>
  `).join('');
}}

function toggleYear(yr) {{
  activeYear = activeYear === yr ? null : yr;
  buildYearChart();
  currentPage = 1;
  applyFilters();
}}

// ── Filter builders ────────────────────────────────────────────────────────
function buildFilters(containerId, mode, activeSet, toggleFn) {{
  const counts = {{}};
  ALL_DATA.forEach(r => {{
    let vals;
    if (mode === 'categories') vals = (r.summary || '').split(',').map(s => s.trim()).filter(Boolean);
    else if (mode === 'sources')   vals = [r.source_name];
    else                           vals = (r.country || '').split(',').map(s => s.trim()).filter(Boolean);
    vals.forEach(v => {{ if (v) counts[v] = (counts[v] || 0) + 1; }});
  }});

  const sorted = Object.entries(counts).sort((a,b) => b[1]-a[1]).slice(0, 20);
  document.getElementById(containerId).innerHTML = sorted.map(([val, count]) => {{
    const safeVal = val.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
    return `<button class="filter-btn ${{activeSet.has(val) ? 'active' : ''}}"
              onclick="${{toggleFn}}('${{safeVal}}')">
      <span>${{esc(val)}}</span>
      <span class="filter-count">${{count}}</span>
    </button>`;
  }}).join('');
}}

function toggleCategory(val) {{
  activeCategories.has(val) ? activeCategories.delete(val) : activeCategories.add(val);
  buildFilters('categoryFilters', 'categories', activeCategories, 'toggleCategory');
  currentPage = 1; applyFilters();
}}
function toggleSource(val) {{
  activeSources.has(val) ? activeSources.delete(val) : activeSources.add(val);
  buildFilters('sourceFilters', 'sources', activeSources, 'toggleSource');
  currentPage = 1; applyFilters();
}}
function toggleCountry(val) {{
  activeCountries.has(val) ? activeCountries.delete(val) : activeCountries.add(val);
  buildFilters('countryFilters', 'countries', activeCountries, 'toggleCountry');
  currentPage = 1; applyFilters();
}}

// ── Search ─────────────────────────────────────────────────────────────────
document.getElementById('searchInput').addEventListener('input', e => {{
  searchQuery = e.target.value.toLowerCase();
  currentPage = 1;
  applyFilters();
}});

// ── Filter & render ────────────────────────────────────────────────────────
function applyFilters() {{
  filtered = ALL_DATA.filter(r => {{
    if (activeYear) {{
      if ((r.date_published || '').slice(0,4) !== activeYear) return false;
    }}
    if (activeCategories.size > 0) {{
      const cats = (r.summary || '').split(',').map(s => s.trim());
      if (!cats.some(c => activeCategories.has(c))) return false;
    }}
    if (activeSources.size > 0 && !activeSources.has(r.source_name)) return false;
    if (activeCountries.size > 0) {{
      const cs = (r.country || '').split(',').map(s => s.trim());
      if (!cs.some(c => activeCountries.has(c))) return false;
    }}
    if (searchQuery) {{
      const hay = [r.title, r.organisation, r.country, r.summary, r.source_name]
        .join(' ').toLowerCase();
      if (!hay.includes(searchQuery)) return false;
    }}
    return true;
  }});
  render();
}}

function render() {{
  const sort = document.getElementById('sortSelect').value;
  const sorted = [...filtered].sort((a, b) => {{
    if (sort === 'date_desc') return (b.date_published||'') > (a.date_published||'') ? 1 : -1;
    if (sort === 'date_asc')  return (a.date_published||'') > (b.date_published||'') ? 1 : -1;
    if (sort === 'title_asc') return (a.title||'').localeCompare(b.title||'');
    if (sort === 'org_asc')   return (a.organisation||'').localeCompare(b.organisation||'');
    return 0;
  }});

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = 1;
  const page = sorted.slice((currentPage-1)*PAGE_SIZE, currentPage*PAGE_SIZE);

  document.getElementById('resultCount').innerHTML =
    `Showing <strong>${{sorted.length}}</strong> of ${{ALL_DATA.length}} use cases`;

  if (sorted.length === 0) {{
    document.getElementById('cards').innerHTML =
      `<div class="no-results"><p>No results</p><p>Try adjusting your filters</p></div>`;
    document.getElementById('pagination').innerHTML = '';
    return;
  }}

  document.getElementById('cards').innerHTML = page.map(r => {{
    const date  = (r.date_published || '—').slice(0, 7);
    const cats  = (r.summary||'').split(',').map(s=>s.trim()).filter(Boolean).slice(0,3);
    const title = r.url
      ? `<a href="${{esc(r.url)}}" target="_blank" rel="noopener">${{esc(r.title||'Untitled')}}</a>`
      : esc(r.title || 'Untitled');
    return `
      <div class="card">
        <div class="card-title">${{title}}</div>
        <div class="card-date">${{date}}</div>
        <div class="card-meta">
          ${{r.organisation ? `<span>🏢 ${{esc(r.organisation)}}</span>` : ''}}
          ${{r.country ? `<span class="tag country">${{esc(r.country.split(',')[0].trim())}}</span>` : ''}}
          <span class="tag source">${{esc(r.source_name)}}</span>
          ${{cats.map(c => `<span class="tag">${{esc(c)}}</span>`).join('')}}
        </div>
      </div>`;
  }}).join('');

  // Pagination
  const pages = [];
  if (totalPages > 1) {{
    pages.push(`<button class="page-btn" ${{currentPage===1?'disabled':''}} onclick="goPage(${{currentPage-1}})">←</button>`);
    for (let i = 1; i <= totalPages; i++) {{
      if (i === 1 || i === totalPages || Math.abs(i - currentPage) <= 2) {{
        pages.push(`<button class="page-btn ${{i===currentPage?'active':''}}" onclick="goPage(${{i}})">${{i}}</button>`);
      }} else if (Math.abs(i - currentPage) === 3) {{
        pages.push(`<span style="padding:6px 4px;color:var(--muted);font-size:11px">…</span>`);
      }}
    }}
    pages.push(`<button class="page-btn" ${{currentPage===totalPages?'disabled':''}} onclick="goPage(${{currentPage+1}})">→</button>`);
  }}
  document.getElementById('pagination').innerHTML = pages.join('');
}}

function goPage(p) {{ currentPage = p; render(); window.scrollTo(0,0); }}

function resetAll() {{
  activeYear = null;
  activeCategories.clear();
  activeSources.clear();
  activeCountries.clear();
  searchQuery = '';
  document.getElementById('searchInput').value = '';
  document.getElementById('sortSelect').value = 'date_desc';
  currentPage = 1;
  buildYearChart();
  buildFilters('categoryFilters', 'categories', activeCategories, 'toggleCategory');
  buildFilters('sourceFilters',   'sources',    activeSources,    'toggleSource');
  buildFilters('countryFilters',  'countries',  activeCountries,  'toggleCountry');
  applyFilters();
}}

function esc(s) {{
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

// ── Init ───────────────────────────────────────────────────────────────────
buildStats();
buildYearChart();
buildFilters('categoryFilters', 'categories', activeCategories, 'toggleCategory');
buildFilters('sourceFilters',   'sources',    activeSources,    'toggleSource');
buildFilters('countryFilters',  'countries',  activeCountries,  'toggleCountry');
applyFilters();
</script>
</body>
</html>"""


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate dashboard.html from the use cases database")
    parser.add_argument("--db",     default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--output", default=str(ROOT_DIR / "dashboard.html"), help="Output HTML file path")
    args = parser.parse_args()

    db_path  = Path(args.db)
    out_path = Path(args.output)

    if not db_path.exists():
        print(f"Error: database not found at {db_path}")
        print("Run some scrapers first to populate the database.")
        sys.exit(1)

    print(f"Reading database: {db_path}")
    data, stats = load_data(db_path)
    print(f"  {stats['total']} records loaded")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(data, stats, generated_at)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    size_kb = out_path.stat().st_size // 1024
    print(f"Dashboard written: {out_path}  ({size_kb} KB)")
    print(f"Open in your browser: file://{out_path.resolve()}")


if __name__ == "__main__":
    main()
