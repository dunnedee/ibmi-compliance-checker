"""
report_generator.py
--------------------
Renders a list of CheckResult objects into a client-facing HTML report and a CSV.
"""

import csv
import html
import datetime
from collections import OrderedDict

PRODUCT_NAME = "ibmi-compliance-checker"

STATUS_META = {
    "PASS":   {"color": "#167C3D", "bg": "#EAF7EF", "label": "Pass"},
    "FAIL":   {"color": "#B42318", "bg": "#FDECEA", "label": "Fail"},
    "REVIEW": {"color": "#A15C07", "bg": "#FCF3E3", "label": "Review"},
    "ERROR":  {"color": "#55606E", "bg": "#EEF0F3", "label": "Error"},
}
STATUS_ORDER = ["PASS", "FAIL", "REVIEW", "ERROR"]


def _esc(text):
    return html.escape(str(text)) if text is not None else ""


def _search_blob(r):
    return _esc(f"{r.check_id} {r.name} {r.category} {r.cis_ref} {r.command_used}").lower()


# ---------- static CSS / JS (plain strings - no .format()/f-string brace conflicts) ----------

_CSS = """
:root {
  --ink: #0E1420;
  --ink-2: #1B2536;
  --paper: #F5F6F8;
  --card: #FFFFFF;
  --line: #E3E7EE;
  --text: #171B24;
  --muted: #5B6472;
  --faint: #8A93A3;
  --brand: #0C7C82;
  --brand-dark: #0A6469;
  --pass: #167C3D;   --pass-bg: #EAF7EF;
  --fail: #B42318;   --fail-bg: #FDECEA;
  --review: #A15C07; --review-bg: #FCF3E3;
  --error: #55606E;  --error-bg: #EEF0F3;
  --serif: Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
  --mono: "SF Mono", SFMono-Regular, "IBM Plex Mono", Menlo, Consolas, "Liberation Mono", monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: var(--sans);
  background: var(--paper);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
  line-height: 1.5;
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 0 28px 64px; }

/* ---- masthead ---- */
.masthead {
  background: linear-gradient(155deg, var(--ink) 0%, var(--ink-2) 100%);
  color: #E9EDF3;
  padding: 40px 0 34px;
  margin-bottom: 28px;
}
.masthead-inner { max-width: 1080px; margin: 0 auto; padding: 0 28px; }
.wordmark {
  display: flex; align-items: center; gap: 10px;
  font-family: var(--mono);
  font-size: 13px;
  letter-spacing: 0.02em;
  color: #9FE8E5;
  margin-bottom: 22px;
}
.wordmark .mark { flex-shrink: 0; }
.report-title {
  font-family: var(--serif);
  font-size: 32px;
  font-weight: 400;
  margin: 0 0 6px;
  color: #FFFFFF;
}
.report-subtitle {
  font-size: 14px;
  color: #B7C0CE;
  margin: 0 0 26px;
  max-width: 640px;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 18px;
  border-top: 1px solid rgba(255,255,255,0.14);
  padding-top: 18px;
}
.meta-grid .k {
  display: block;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #8894A6;
  margin-bottom: 4px;
}
.meta-grid .v { font-size: 13.5px; color: #EDF0F4; word-break: break-word; }

/* ---- executive summary ---- */
.exec {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 28px 30px;
  margin-bottom: 22px;
  display: grid;
  grid-template-columns: 150px 1fr;
  gap: 32px;
  align-items: center;
}
.donut {
  width: 128px; height: 128px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  position: relative;
  flex-shrink: 0;
}
.donut::after {
  content: "";
  position: absolute;
  width: 82px; height: 82px;
  border-radius: 50%;
  background: var(--card);
}
.donut .donut-label {
  position: relative; z-index: 1; text-align: center;
}
.donut .pct { font-family: var(--serif); font-size: 24px; color: var(--ink); display: block; line-height: 1.1; }
.donut .pct-lbl { font-size: 9.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.exec-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; }
.stat {
  padding: 0 18px;
  border-left: 3px solid var(--line);
}
.stat:first-child { padding-left: 0; }
.stat.st-pass { border-left-color: var(--pass); }
.stat.st-fail { border-left-color: var(--fail); }
.stat.st-review { border-left-color: var(--review); }
.stat.st-error { border-left-color: var(--error); }
.stat .stat-num { font-family: var(--serif); font-size: 26px; color: var(--ink); display: block; }
.stat .stat-lbl { font-size: 12px; color: var(--muted); margin-top: 2px; }

/* ---- controls bar ---- */
.controls {
  position: sticky; top: 0; z-index: 10;
  background: rgba(245,246,248,0.92);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid var(--line);
  padding: 14px 0;
  margin-bottom: 20px;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.filter-pill {
  font-family: var(--sans);
  font-size: 12.5px;
  padding: 6px 13px;
  border-radius: 100px;
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--muted);
  cursor: pointer;
  user-select: none;
  transition: border-color 0.12s, color 0.12s;
}
.filter-pill:hover { border-color: var(--brand); color: var(--brand-dark); }
.filter-pill.active { background: var(--ink); color: #fff; border-color: var(--ink); }
.search-box {
  margin-left: auto;
  font-family: var(--sans);
  font-size: 13px;
  padding: 7px 14px;
  border-radius: 100px;
  border: 1px solid var(--line);
  background: var(--card);
  width: 240px;
  color: var(--text);
}
.search-box:focus { outline: none; border-color: var(--brand); }

/* ---- category groups ---- */
.category { margin-bottom: 12px; }
.category > summary {
  list-style: none;
  cursor: pointer;
  display: flex; align-items: center; gap: 10px;
  padding: 13px 16px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}
.category > summary::-webkit-details-marker { display: none; }
.category > summary .chev { color: var(--faint); font-size: 11px; transition: transform 0.15s; margin-left: auto; }
.category[open] > summary .chev { transform: rotate(90deg); }
.category > summary .cat-count { font-weight: 400; color: var(--muted); font-size: 12.5px; }
.category-body { padding: 8px 0 0 0; }

/* ---- check item ---- */
.check-item { border: 1px solid var(--line); border-top: none; background: var(--card); }
.check-item:first-child { border-top: 1px solid var(--line); border-radius: 10px 10px 0 0; }
.check-item:last-child { border-radius: 0 0 10px 10px; }
.check-item > summary {
  list-style: none;
  cursor: pointer;
  display: grid;
  grid-template-columns: 74px 90px 1fr 96px 18px;
  gap: 14px;
  align-items: center;
  padding: 12px 16px;
}
.check-item > summary::-webkit-details-marker { display: none; }
.check-item .cid { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.check-item .cref { font-family: var(--mono); font-size: 11.5px; color: var(--faint); }
.check-item .cname { font-size: 13.5px; color: var(--text); }
.status-pill {
  display: inline-block;
  font-size: 11px; font-weight: 700;
  padding: 3px 11px; border-radius: 100px;
  letter-spacing: 0.02em;
  text-align: center;
  justify-self: start;
}
.check-item .chev { color: var(--faint); font-size: 11px; transition: transform 0.15s; justify-self: end; }
.check-item[open] .chev { transform: rotate(90deg); }
.check-item[open] > summary { border-bottom: 1px solid var(--line); }
.check-body { padding: 16px 16px 18px 16px; display: grid; gap: 14px; }
.block-label {
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.07em;
  color: var(--faint); margin-bottom: 5px;
}
.block-code {
  font-family: var(--mono); font-size: 12px; color: var(--text);
  background: var(--paper); border: 1px solid var(--line); border-radius: 7px;
  padding: 10px 12px; white-space: pre-wrap; word-break: break-word;
}
.block-text { font-size: 13px; color: var(--text); }
.check-item.hidden { display: none; }
.category.hidden { display: none; }

/* ---- footer ---- */
.report-footer {
  margin-top: 36px; padding-top: 20px; border-top: 1px solid var(--line);
  font-size: 11.5px; color: var(--faint); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
}

@media print {
  .controls { position: static; backdrop-filter: none; }
  .search-box, .filter-pill { display: none; }
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .donut { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""

_JS = """
(function() {
  var items = Array.prototype.slice.call(document.querySelectorAll('.check-item'));
  var cats = Array.prototype.slice.call(document.querySelectorAll('.category'));
  var pills = Array.prototype.slice.call(document.querySelectorAll('.filter-pill'));
  var search = document.getElementById('search');
  var active = 'ALL';

  function apply() {
    var q = (search.value || '').toLowerCase().trim();
    cats.forEach(function(cat) {
      var anyVisible = false;
      var catItems = cat.querySelectorAll('.check-item');
      catItems.forEach(function(item) {
        var statusOk = (active === 'ALL') || (item.getAttribute('data-status') === active);
        var searchOk = !q || item.getAttribute('data-search').indexOf(q) !== -1;
        var show = statusOk && searchOk;
        item.classList.toggle('hidden', !show);
        if (show) anyVisible = true;
      });
      cat.classList.toggle('hidden', !anyVisible);
      if (q && anyVisible) { cat.setAttribute('open', ''); }
    });
  }

  pills.forEach(function(pill) {
    pill.addEventListener('click', function() {
      pills.forEach(function(p) { p.classList.remove('active'); });
      pill.classList.add('active');
      active = pill.getAttribute('data-status');
      apply();
    });
  });
  search.addEventListener('input', apply);

  var openBeforePrint = [];
  window.addEventListener('beforeprint', function() {
    openBeforePrint = [];
    document.querySelectorAll('details').forEach(function(d) {
      openBeforePrint.push([d, d.hasAttribute('open')]);
      d.setAttribute('open', '');
    });
  });
  window.addEventListener('afterprint', function() {
    openBeforePrint.forEach(function(pair) {
      if (!pair[1]) pair[0].removeAttribute('open');
    });
  });
})();
"""

_LOGOMARK_SVG = (
    '<svg class="mark" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<rect width="16" height="16" rx="4" fill="#0C7C82"/>'
    '<path d="M4.2 8.3L6.8 10.9L11.8 5.4" stroke="#0B1120" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)


def _donut_gradient(counts, total):
    if total == 0:
        return "#E3E7EE"
    stops = []
    cum = 0.0
    for status in STATUS_ORDER:
        n = counts.get(status, 0)
        if n == 0:
            continue
        start = cum
        cum += (n / total) * 100
        stops.append(f"{STATUS_META[status]['color']} {start:.3f}% {cum:.3f}%")
    if not stops:
        return "#E3E7EE"
    return "conic-gradient(" + ", ".join(stops) + ")"


def generate_html(results, meta, output_path):
    """
    meta: dict with keys like target, mode, tester, engagement, generated_at
    """
    total = len(results)
    counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "ERROR": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    pass_rate = round((counts["PASS"] / total) * 100) if total else 0

    # group by category, preserving first-seen order
    grouped = OrderedDict()
    for r in results:
        grouped.setdefault(r.category, []).append(r)

    category_html_parts = []
    for category, rows in grouped.items():
        item_parts = []
        for r in rows:
            sm = STATUS_META.get(r.status, STATUS_META["ERROR"])
            item_parts.append(f"""
        <details class="check-item" data-status="{_esc(r.status)}" data-search="{_search_blob(r)}">
          <summary>
            <span class="cid">{_esc(r.check_id)}</span>
            <span class="cref">{_esc(r.cis_ref) or '—'}</span>
            <span class="cname">{_esc(r.name)}</span>
            <span class="status-pill" style="color:{sm['color']};background:{sm['bg']}">{sm['label']}</span>
            <span class="chev">&#9656;</span>
          </summary>
          <div class="check-body">
            <div>
              <div class="block-label">Command / query used</div>
              <div class="block-code">{_esc(r.command_used)}</div>
            </div>
            <div>
              <div class="block-label">Evidence / output</div>
              <div class="block-code">{_esc(r.evidence)}</div>
            </div>
            <div>
              <div class="block-label">Recommendation</div>
              <div class="block-text">{_esc(r.recommendation)}</div>
            </div>
          </div>
        </details>""")
        category_html_parts.append(f"""
    <details class="category" open>
      <summary>
        {_esc(category)}
        <span class="cat-count">({len(rows)})</span>
        <span class="chev">&#9656;</span>
      </summary>
      <div class="category-body">{''.join(item_parts)}</div>
    </details>""")

    donut_bg = _donut_gradient(counts, total)

    pill_defs = [("ALL", f"All ({total})")] + [
        (s, f"{STATUS_META[s]['label']} ({counts[s]})") for s in STATUS_ORDER
    ]
    pills_html = "".join(
        f'<button type="button" class="filter-pill{" active" if code == "ALL" else ""}" data-status="{code}">{label}</button>'
        for code, label in pill_defs
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PRODUCT_NAME} — IBM i Configuration Compliance Report</title>
<style>{_CSS}</style>
</head>
<body>

  <div class="masthead">
    <div class="masthead-inner">
      <div class="wordmark">{_LOGOMARK_SVG}<span>{PRODUCT_NAME}</span></div>
      <h1 class="report-title">IBM i Configuration Compliance Report</h1>
      <p class="report-subtitle">Automated hardening review against the CIS IBM i Benchmark. Review every Fail and Review item before the findings are considered final.</p>
      <div class="meta-grid">
        <div><span class="k">Target</span><span class="v">{_esc(meta.get('target', '') or '—')}</span></div>
        <div><span class="k">Connection mode</span><span class="v">{_esc((meta.get('mode', '') or '').upper() or '—')}</span></div>
        <div><span class="k">Tester</span><span class="v">{_esc(meta.get('tester', '') or '—')}</span></div>
        <div><span class="k">Engagement</span><span class="v">{_esc(meta.get('engagement', '') or '—')}</span></div>
        <div><span class="k">Generated</span><span class="v">{_esc(meta.get('generated_at', '') or '—')}</span></div>
      </div>
    </div>
  </div>

  <div class="wrap">

    <div class="exec">
      <div class="donut" style="background:{donut_bg}">
        <div class="donut-label"><span class="pct">{pass_rate}%</span><span class="pct-lbl">Pass rate</span></div>
      </div>
      <div class="exec-stats">
        <div class="stat st-pass"><span class="stat-num">{counts['PASS']}</span><span class="stat-lbl">Pass</span></div>
        <div class="stat st-fail"><span class="stat-num">{counts['FAIL']}</span><span class="stat-lbl">Fail</span></div>
        <div class="stat st-review"><span class="stat-num">{counts['REVIEW']}</span><span class="stat-lbl">Review</span></div>
        <div class="stat st-error"><span class="stat-num">{counts['ERROR']}</span><span class="stat-lbl">Error</span></div>
      </div>
    </div>

    <div class="controls">
      {pills_html}
      <input type="text" id="search" class="search-box" placeholder="Search checks…">
    </div>

    {''.join(category_html_parts)}

    <div class="report-footer">
      <span>Generated by {PRODUCT_NAME} — read-only configuration checks, no changes made to the target system.</span>
      <span>{_esc(meta.get('generated_at', ''))}</span>
    </div>

  </div>

<script>{_JS}</script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return output_path


def generate_csv(results, output_path):
    fieldnames = ["check_id", "cis_ref", "name", "category", "status",
                  "command_used", "evidence", "recommendation", "timestamp"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "check_id": r.check_id,
                "cis_ref": r.cis_ref,
                "name": r.name,
                "category": r.category,
                "status": r.status,
                "command_used": r.command_used,
                "evidence": r.evidence,
                "recommendation": r.recommendation,
                "timestamp": r.timestamp,
            })
    return output_path



def generate_csv(results, output_path):
    fieldnames = ["check_id", "cis_ref", "name", "category", "status",
                  "command_used", "evidence", "recommendation", "timestamp"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "check_id": r.check_id,
                "cis_ref": r.cis_ref,
                "name": r.name,
                "category": r.category,
                "status": r.status,
                "command_used": r.command_used,
                "evidence": r.evidence,
                "recommendation": r.recommendation,
                "timestamp": r.timestamp,
            })
    return output_path
