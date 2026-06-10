#!/usr/bin/env python3
"""
Generate publications.html from the ADS library.

Usage:
    python generate_publications.py

The script fetches all papers from the ADS library, then writes a fresh
publications.html into the same directory. Run it whenever you want to
update the page with new papers or citation counts.

Requirements:
    pip install requests
"""

import os
import re
import html as html_module
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY    = os.getenv("ADS_API_KEY",    "m2WhxZnX56sVSewEwcEORL9szXB1JBm7GwE3hW1k")
LIBRARY_ID = os.getenv("ADS_LIBRARY_ID", "PK0RWOWOTIKWfo-5Fck9sg")

OUT_FILE   = Path(__file__).parent / "publications.html"

FIRST_AUTHOR_RE = re.compile(
    r"^Winter,\s+(Andrew(?:\s+J\.?)*\.?|A\.(?:\s*J\.?)?)\s*$", re.IGNORECASE
)

# doctype groups
ARTICLE_TYPES    = {"article", "eprint", "bookreview", "erratum", "techreport", "intechreport"}
CONFERENCE_TYPES = {"inproceedings", "proceedings", "abstract", "talk"}
PROPOSAL_TYPES   = {"proposal"}

JOURNAL_SHORT = {
    "monthly notices of the royal astronomical society": "MNRAS",
    "mnras": "MNRAS",
    "the astrophysical journal": "ApJ",
    "astrophysical journal": "ApJ",
    "the astrophysical journal letters": "ApJL",
    "astrophysical journal letters": "ApJL",
    "the astrophysical journal supplement series": "ApJS",
    "the astronomical journal": "AJ",
    "astronomical journal": "AJ",
    "astronomy & astrophysics": "A&A",
    "astronomy and astrophysics": "A&A",
    "a&a": "A&A",
    "nature astronomy": "Nature Astronomy",
    "nature": "Nature",
    "publications of the astronomical society of australia": "PASA",
    "publications of the astronomical society of the pacific": "PASP",
    "the open journal of astrophysics": "OJAp",
    "open journal of astrophysics": "OJAp",
    "arxiv e-prints": "arXiv",
}


# ── ADS helpers ───────────────────────────────────────────────────────────────

def ads_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
    }


def fetch_all_bibcodes():
    bibcodes, start, page_size = [], 0, 2000
    while True:
        r = requests.get(
            f"https://api.adsabs.harvard.edu/v1/biblib/libraries/{LIBRARY_ID}",
            headers=ads_headers(),
            params={"rows": page_size, "start": start},
            timeout=60,
        )
        r.raise_for_status()
        data  = r.json()
        batch = data.get("documents", [])
        bibcodes.extend(batch)
        total = data.get("metadata", {}).get("num_documents", len(bibcodes))
        print(f"  bibcodes: {len(bibcodes)}/{total}")
        if len(bibcodes) >= total or not batch:
            break
        start += page_size
    return bibcodes


def fetch_metadata(bibcodes):
    docs, batch_size = [], 100
    for i in range(0, len(bibcodes), batch_size):
        batch = bibcodes[i : i + batch_size]
        q = " OR ".join(f'bibcode:"{bc}"' for bc in batch)
        r = requests.get(
            "https://api.adsabs.harvard.edu/v1/search/query",
            headers=ads_headers(),
            params={
                "q": q,
                "fl": "bibcode,title,author,author_count,pub,year,pubdate,citation_count,doi,doctype",
                "rows": batch_size,
            },
            timeout=60,
        )
        r.raise_for_status()
        docs.extend(r.json().get("response", {}).get("docs", []))
        print(f"  metadata: {len(docs)} fetched")
    return docs


def shorten_journal(raw):
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    raw = (raw or "").strip()
    return JOURNAL_SHORT.get(raw.lower(), raw)


def parse_year(pubdate):
    try:
        return int(pubdate[:4])
    except (TypeError, ValueError):
        return 0


def is_first_author(doc):
    authors = doc.get("author") or []
    return bool(authors and FIRST_AUTHOR_RE.match(authors[0]))


def categorise(doc):
    dt = (doc.get("doctype") or "article").lower()
    if dt in CONFERENCE_TYPES:
        return "conference"
    if dt in PROPOSAL_TYPES:
        return "proposal"
    return "article"


def author_display(raw):
    """Convert 'Last, First Middle' → 'F. M. Last'."""
    if "," in raw:
        last, first = raw.split(",", 1)
        inits = " ".join(p[0] + "." for p in first.strip().split() if p)
        return f"{inits} {last.strip()}"
    return raw.strip()


def format_authors(doc):
    """Return HTML author string, bolding any Winter, A* variant.

    If my name falls outside the first 5 authors the string reads:
        Author1, Author2, Author3, …, <strong>A. Winter</strong>, et al.
    """
    authors  = doc.get("author") or []
    nauthors = int(doc.get("author_count") or len(authors))
    MAX_SHOW = 5

    # Locate my name once across the full list
    me_idx, me_raw = None, None
    for i, a in enumerate(authors):
        if FIRST_AUTHOR_RE.match(a):
            me_idx, me_raw = i, a
            break

    parts = []

    if me_idx is not None and me_idx < MAX_SHOW:
        # My name is within the first 5 — show up to MAX_SHOW authors normally
        for i, a in enumerate(authors[:MAX_SHOW]):
            display = author_display(a)
            if i == me_idx:
                display = f"<strong>{display}</strong>"
            parts.append(display)
        if nauthors > MAX_SHOW:
            parts.append("<em>et al.</em>")
    else:
        # My name is beyond position 5 — show first 3, ellipsis, my name, et al.
        for a in authors[:3]:
            parts.append(author_display(a))
        parts.append("&hellip;")
        if me_raw:
            parts.append(f"<strong>{author_display(me_raw)}</strong>")
        parts.append("<em>et al.</em>")

    return ", ".join(parts)


def ads_url(bibcode):
    return f"https://ui.adsabs.harvard.edu/abs/{requests.utils.quote(bibcode)}/abstract"


# ── HTML helpers ──────────────────────────────────────────────────────────────

NAV = """\
  <nav>
    <div class="nav-inner">
      <a href="index.html" class="nav-brand">A. J. Winter</a>
      <button class="nav-toggle" aria-label="Toggle menu"
              onclick="this.nextElementSibling.classList.toggle('open')">
        <span></span><span></span><span></span>
      </button>
      <ul class="nav-links">
        <li><a href="index.html">Home</a></li>
        <li><a href="research.html">Research</a></li>
        <li><a href="teaching.html">Teaching</a></li>
        <li><a href="cv.html">CV</a></li>
        <li><a href="publications.html" class="active">Publications</a></li>
      </ul>
    </div>
  </nav>"""


def build_entry(doc, show_cites=True):
    title    = html_module.unescape(
        (doc.get("title") or ["(no title)"])[0]
        if isinstance(doc.get("title"), list)
        else (doc.get("title") or "(no title)")
    )
    journal  = shorten_journal(doc.get("pub"))
    year     = parse_year(doc.get("pubdate", ""))
    cites    = int(doc.get("citation_count") or 0)
    bibcode  = doc.get("bibcode", "")
    first    = is_first_author(doc)

    badge = (
        '<span class="badge badge-first">First author</span>'
        if first else
        '<span class="badge badge-coauth">Co-author</span>'
    )
    data_type = "first" if first else "coauth"

    cite_str = (
        f'&ensp;<span class="pub-cites">{cites} citations</span>'
        if (show_cites and cites) else ""
    )

    return f"""\
          <div class="pub-entry" data-type="{data_type}">
            <div class="pub-badge">{badge}</div>
            <div>
              <div class="pub-title">{html_module.escape(title)}</div>
              <div class="pub-authors">{format_authors(doc)}</div>
              <div class="pub-journal"><em>{html_module.escape(journal)}</em>{(', ' + str(year)) if year else ''}{cite_str}</div>
              <div class="pub-links">
                <a href="{ads_url(bibcode)}" target="_blank" rel="noopener" class="pub-link">ADS &#8599;</a>
              </div>
            </div>
          </div>"""


def build_year_groups(docs, show_cites=True):
    by_year = defaultdict(list)
    for d in sorted(docs, key=lambda d: d.get("pubdate", ""), reverse=True):
        by_year[parse_year(d.get("pubdate", ""))].append(d)

    blocks = []
    for yr in sorted(by_year.keys(), reverse=True):
        entries = "\n".join(build_entry(d, show_cites) for d in by_year[yr])
        label   = str(yr) if yr else "Unknown"
        blocks.append(f"""\
        <div class="pub-year-group">
          <div class="pub-year-label">{label}</div>
{entries}
        </div>""")
    return "\n".join(blocks)


def tab_section(tab_id, label, docs, show_cites=True, extra_note=""):
    n_first  = sum(1 for d in docs if is_first_author(d))
    n_total  = len(docs)
    year_html = build_year_groups(docs, show_cites)
    note_html = f'<p class="updated-note" style="margin-bottom:1rem;">{extra_note}</p>' if extra_note else ""
    return f"""\
      <!-- ===== TAB: {label} ===== -->
      <div id="tab-{tab_id}" class="tab-panel" style="display:none;">

        <div class="pub-filter-bar">
          <span style="font-size:.82rem;color:var(--text-muted);font-weight:600;">Filter:</span>
          <button class="filter-btn active" onclick="filterPubs('{tab_id}','all',this)">All ({n_total})</button>
          <button class="filter-btn" onclick="filterPubs('{tab_id}','first',this)">First-author ({n_first})</button>
          <button class="filter-btn" onclick="filterPubs('{tab_id}','coauth',this)">Co-author ({n_total - n_first})</button>
        </div>
        {note_html}
{year_html}

      </div>"""


# ── Page builder ──────────────────────────────────────────────────────────────

def build_html(docs):
    articles    = [d for d in docs if categorise(d) == "article"]
    conferences = [d for d in docs if categorise(d) == "conference"]
    proposals   = [d for d in docs if categorise(d) == "proposal"]

    n_articles    = len(articles)
    n_conferences = len(conferences)
    n_proposals   = len(proposals)
    n_total       = len(docs)
    n_first       = sum(1 for d in articles if is_first_author(d))

    now = datetime.utcnow().strftime("%d %b %Y")

    articles_html    = tab_section("articles",    "Journal Articles", articles,    show_cites=True)
    conferences_html = tab_section("conferences", "Conference Talks", conferences, show_cites=False)
    proposals_html   = tab_section("proposals",   "Observing Proposals", proposals, show_cites=False,
                                   extra_note="JWST and other facility proposals as listed on NASA ADS.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Publications — A. J. Winter</title>
  <meta name="description" content="Full publication list of Andrew J. Winter — astrophysicist at QMUL.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="css/style.css">
  <style>
    /* ── tab nav ── */
    .tab-nav {{
      display: flex; gap: 0; border-bottom: 2px solid var(--border);
      margin-bottom: 2.5rem; flex-wrap: wrap;
    }}
    .tab-btn {{
      padding: .65rem 1.4rem; border: none; background: transparent;
      font-family: var(--font-sans); font-size: .9rem; font-weight: 600;
      color: var(--text-muted); cursor: pointer; border-bottom: 3px solid transparent;
      margin-bottom: -2px; transition: all .2s;
    }}
    .tab-btn:hover {{ color: var(--text); }}
    .tab-btn.active {{ color: var(--navy); border-bottom-color: var(--accent); }}
    /* ── filter bar ── */
    .pub-filter-bar {{
      display: flex; align-items: center; gap: .75rem;
      flex-wrap: wrap; margin-bottom: 2rem;
    }}
    .filter-btn {{
      padding: .4rem 1rem; border-radius: 999px;
      border: 1.5px solid var(--border); background: transparent;
      font-size: .82rem; font-weight: 600; color: var(--text-muted);
      cursor: pointer; transition: all .2s; font-family: var(--font-sans);
    }}
    .filter-btn:hover, .filter-btn.active {{
      background: var(--navy); border-color: var(--navy); color: #fff;
    }}
    /* ── stats ── */
    .pub-stats {{
      display: flex; gap: 2rem; flex-wrap: wrap;
      background: var(--bg-light); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 1.25rem 1.75rem; margin-bottom: 2rem;
    }}
    .pub-stat strong {{ display: block; font-size: 1.5rem; font-family: var(--font-serif); color: var(--navy); line-height: 1; }}
    .pub-stat span {{ font-size: .8rem; color: var(--text-muted); }}
    /* ── year groups + entries ── */
    .pub-year-group {{ margin-bottom: 2.5rem; }}
    .pub-year-label {{
      font-family: var(--font-serif); font-size: 1.4rem; color: var(--navy);
      border-bottom: 2px solid var(--border); padding-bottom: .4rem; margin-bottom: 1.25rem;
    }}
    .pub-entry {{
      display: grid; grid-template-columns: auto 1fr;
      gap: 0 1.25rem; padding: 1rem 0; border-bottom: 1px solid var(--border);
      transition: background .15s;
    }}
    .pub-entry:last-child {{ border-bottom: none; }}
    .pub-entry:hover {{
      background: var(--bg-light);
      margin: 0 -.75rem; padding-left: .75rem; padding-right: .75rem;
      border-radius: 6px;
    }}
    .pub-badge {{ margin-top: 3px; flex-shrink: 0; }}
    .badge {{
      display: inline-block; font-size: .65rem; font-weight: 700;
      letter-spacing: .07em; text-transform: uppercase;
      padding: .2rem .55rem; border-radius: 4px; white-space: nowrap;
    }}
    .badge-first  {{ background: rgba(46,134,193,.12); color: var(--accent); border: 1px solid rgba(46,134,193,.3); }}
    .badge-coauth {{ background: rgba(212,168,67,.12); color: #a07830; border: 1px solid rgba(212,168,67,.3); }}
    .pub-title   {{ font-weight: 600; font-size: .95rem; color: var(--text); line-height: 1.4; margin-bottom: .2rem; }}
    .pub-authors {{ font-size: .85rem; color: var(--text-muted); margin-bottom: .2rem; }}
    .pub-authors strong {{ color: var(--text); }}
    .pub-journal {{ font-size: .82rem; color: var(--text-muted); margin-bottom: .35rem; }}
    .pub-cites   {{ font-style: normal; font-size: .78rem; color: var(--text-muted); }}
    .pub-links   {{ display: flex; gap: .5rem; flex-wrap: wrap; }}
    .pub-link {{
      display: inline-flex; align-items: center; gap: .25rem;
      font-size: .78rem; font-weight: 600; padding: .2rem .6rem;
      border-radius: 4px; border: 1px solid var(--border);
      color: var(--text-muted); background: var(--bg); transition: all .15s;
    }}
    .pub-link:hover {{ border-color: var(--accent); color: var(--accent); background: rgba(46,134,193,.05); }}
    .updated-note {{ font-size: .8rem; color: var(--text-muted); margin-bottom: 2rem; }}
  </style>
</head>
<body>

{NAV}

  <header class="page-hero">
    <div class="container">
      <span class="section-label">Research Output</span>
      <h1>Publications</h1>
      <p>Complete list from the
         <a href="https://ui.adsabs.harvard.edu/user/libraries/PK0RWOWOTIKWfo-5Fck9sg"
            target="_blank" rel="noopener"
            style="color:rgba(255,255,255,.8);text-decoration:underline;">NASA ADS library</a>.
         Automatically updated weekly.</p>
    </div>
  </header>

  <main>
    <section>
      <div class="container">

        <div class="pub-stats">
          <div class="pub-stat">
            <strong>{n_first}</strong>
            <span>First-author papers</span>
          </div>
          <div class="pub-stat">
            <strong>{n_articles}</strong>
            <span>Journal articles</span>
          </div>
          <div class="pub-stat">
            <strong><a href="https://ui.adsabs.harvard.edu/user/libraries/PK0RWOWOTIKWfo-5Fck9sg"
                       target="_blank" rel="noopener">ADS &#8599;</a></strong>
            <span>Full library</span>
          </div>
        </div>

        <p class="updated-note">Last updated: {now} UTC</p>

        <!-- Tab navigation -->
        <div class="tab-nav">
          <button class="tab-btn active" onclick="switchTab('articles', this)">
            Journal Articles ({n_articles})
          </button>
          <button class="tab-btn" onclick="switchTab('conferences', this)">
            Published Conference Talks ({n_conferences})
          </button>
          <button class="tab-btn" onclick="switchTab('proposals', this)">
            Published Observing Proposals ({n_proposals})
          </button>
        </div>

{articles_html}
{conferences_html}
{proposals_html}

      </div>
    </section>
  </main>

  <section class="contact-section">
    <div class="container">
      <p class="section-label">Get in Touch</p>
      <h2 class="section-heading">Contact</h2>
      <p>For questions about any of my research, please get in touch.</p>
      <div class="contact-grid" style="margin-top:2rem;">
        <div class="contact-item">
          <div class="contact-icon">&#9993;</div>
          <div class="contact-item-text">
            <small>Email</small>
            <a href="mailto:andrew.winter@qmul.ac.uk">andrew.winter@qmul.ac.uk</a>
          </div>
        </div>
        <div class="contact-item">
          <div class="contact-icon">&#128196;</div>
          <div class="contact-item-text">
            <small>Full ADS library</small>
            <a href="https://ui.adsabs.harvard.edu/user/libraries/PK0RWOWOTIKWfo-5Fck9sg"
               target="_blank" rel="noopener">NASA ADS &#8599;</a>
          </div>
        </div>
      </div>
    </div>
  </section>

  <footer>
    <p>&copy; 2025 Andrew J. Winter &mdash; Queen Mary University of London</p>
  </footer>

  <script>
    // ── Tab switching ──
    function switchTab(id, btn) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
      btn.classList.add('active');
      document.getElementById('tab-' + id).style.display = '';
    }}
    // Show first tab on load
    document.addEventListener('DOMContentLoaded', () => {{
      document.getElementById('tab-articles').style.display = '';
    }});

    // ── Per-tab first/co-author filter ──
    function filterPubs(tabId, type, btn) {{
      const panel = document.getElementById('tab-' + tabId);
      panel.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      panel.querySelectorAll('.pub-entry').forEach(el => {{
        el.style.display = (type === 'all' || el.dataset.type === type) ? '' : 'none';
      }});
      panel.querySelectorAll('.pub-year-group').forEach(g => {{
        const vis = [...g.querySelectorAll('.pub-entry')].some(e => e.style.display !== 'none');
        g.style.display = vis ? '' : 'none';
      }});
    }}
  </script>

</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Fetching bibcodes from ADS library…")
    bibcodes = fetch_all_bibcodes()
    print(f"Fetching metadata for {len(bibcodes)} papers…")
    docs = fetch_metadata(bibcodes)
    print(f"Building HTML ({len(docs)} papers)…")
    page = build_html(docs)
    OUT_FILE.write_text(page, encoding="utf-8")
    print(f"Written → {OUT_FILE}")
