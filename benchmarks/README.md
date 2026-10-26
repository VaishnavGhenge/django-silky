# UI benchmarks

Two scripts measure the Silk UI so each phase of the redesign can be compared
against the old interface on the same data.

| Script | Measures |
|---|---|
| `server_bench.py` | Server render time (median, p90), DB queries and HTML size for every Silk page, via Django's test client |
| `browser_bench.mjs` | Load time, Largest Contentful Paint, layout shift, main-thread blocking, request count and asset weight, in headless Chromium |

## Running

```bash
# 1. Server side. Seeds a deterministic dataset (random.seed(42)) into
#    benchmarks/.data/bench-<N>.sqlite3 on first run, then reuses it.
.venv/bin/python benchmarks/server_bench.py --requests 200  --label <name>
.venv/bin/python benchmarks/server_bench.py --requests 5000 --label <name>

# 2. Browser side, against a server on the same dataset.
DB_ENGINE=sqlite3 DB_NAME=$PWD/benchmarks/.data/bench-5000.sqlite3 \
  .venv/bin/python project/manage.py runserver 127.0.0.1:8010 --noreload &
node benchmarks/browser_bench.mjs --pages benchmarks/results/<name>-server-5000.json --label <name>
node benchmarks/browser_bench.mjs --pages benchmarks/results/<name>-server-5000.json --label <name> --cpu 4
```

`npm install` provides `playwright-core`, which drives an existing Chromium and
downloads none. Point `CHROMIUM_PATH` at a Chromium binary if Playwright cannot
find one. Results land in `results/` as JSON.

## Baseline: old UI (v1.6.0), recorded 2026-10-25

Apple Silicon laptop, SQLite, Django dev server on localhost. Server times are
medians of 10 renders; browser times are medians of 5 cold loads (fresh context,
empty cache). The large dataset is 5,000 requests, 75,973 queries and 4,885
profiles; the small one is 200 requests.

| Page | Render, 200 req | Render, 5k req | DB queries | HTML, 5k | Load | Load, CPU 4× | LCP, CPU 4× | CLS | Requests | JS | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| summary | 21 ms | **465 ms** | 55 | 31 KB | 501 ms | 613 ms | 632 ms | 0.016 | 22 | 1,026 KB | 1,357 KB |
| requests | 12 ms | 22 ms | **59** | **697 KB** | 75 ms | 180 ms | 196 ms | 0.039 | 29 | 823 KB | 1,852 KB |
| requests, sorted by time | 14 ms | 29 ms | 63 | 701 KB | 83 ms | 193 ms | 208 ms | 0.032 | 29 | 823 KB | 1,857 KB |
| request detail | 4 ms | 4 ms | 6 | 11 KB | 54 ms | 143 ms | 156 ms | 0.005 | 25 | 762 KB | 1,219 KB |
| request SQL | 62 ms | 71 ms | 7 | 84 KB | 119 ms | 210 ms | 232 ms | 0.013 | 29 | 779 KB | 1,331 KB |
| request SQL detail | 2 ms | 1 ms | 4 | 10 KB | 46 ms | 125 ms | 136 ms | 0.020 | 29 | 763 KB | 1,222 KB |
| request profiling | 2 ms | 2 ms | 8 | 15 KB | 47 ms | 128 ms | 136 ms | 0.001 | 30 | 809 KB | 1,157 KB |
| profiling | 8 ms | 9 ms | 31 | 45 KB | 56 ms | 146 ms | 160 ms | 0.028 | 30 | 809 KB | 1,187 KB |
| profile detail | 1 ms | 1 ms | 6 | 8 KB | 53 ms | 131 ms | 144 ms | 0.044 | 29 | **2,447 KB** | 2,852 KB |
| cProfile | 1 ms | 1 ms | 3 | 7 KB | 49 ms | 114 ms | 124 ms | 0.002 | 29 | **2,447 KB** | 2,851 KB |
| clear DB / settings | 0 ms | 0 ms | 0 | 25 KB | 39 ms | 109 ms | 120 ms | 0.010 | 20 | 728 KB | 1,052 KB |

Asset sizes are decoded (uncompressed) bytes. Every filter, sort or page change
in the old UI is a full page load, so the "Load" column is also the cost of
each interaction on that page.

### What the baseline shows

- **Summary grows with data.** 21 ms at 200 requests, 465 ms at 5,000: the page
  aggregates over the whole table on every view.
- **The requests list HTML grows with data.** 100 KB at 200 requests, 697 KB at
  5,000, though it shows the same 25 rows. The path filter renders a checkbox
  for every distinct path ever recorded (1,674 checkboxes at 5,000 requests).
- **Silk's own views run 55 to 63 queries** on the summary and requests pages.
- **Every page ships 730 KB to 1 MB of JavaScript** before it is useful;
  profile pages ship 2.4 MB because the graph library loads on every visit.
- **20 to 30 HTTP requests per page**, mostly separate CSS and JS files.
- **Request SQL renders in about 65 ms** regardless of dataset size: the cost is
  SQL formatting, not the database.
- Layout shift stays under 0.05 everywhere, which is already acceptable.
- Main-thread blocking reads 0 ms: none of the old pages run long tasks, so
  their cost is download size and full reloads rather than script execution.

### Targets for the redesign

| Metric | Old UI | Target |
|---|---|---|
| JS per page (except profile graph) | 728 KB to 1,026 KB | under 100 KB uncompressed |
| HTTP requests per page | 20 to 30 | under 8 |
| Requests HTML at 5k requests | 697 KB | under 120 KB, independent of dataset size |
| Summary render at 5k requests | 465 ms | under 150 ms |
| DB queries on summary / requests | 55 / 59 | under 15 each |
| Filter, sort or page change | full reload (180 ms at CPU 4×) | partial update, under 100 ms at CPU 4× |
| CLS | up to 0.044 | under 0.05 (keep) |

## Phase 1: foundation, recorded 2026-10-25

New shell (sidebar, themes, accents), inline icon sprite instead of the Lucide
script, jQuery UI and other unused libraries removed, one stylesheet for the
shell. Page content is unchanged, so server render times and query counts are
the same as the baseline. Browser figures at CPU 4×, 5,000 requests:

| Page | JS | Total transfer | Requests | Load | CLS |
|---|---:|---:|---:|---:|---:|
| summary | 1,026 → **391 KB** | 1,357 → 575 KB | 22 → 13 | 613 → 617 ms | 0.016 → 0.008 |
| requests | 822 → **189 KB** | 1,852 → 1,071 KB | 29 → 21 | 180 → 157 ms | 0.038 → 0.002 |
| request detail | 762 → **127 KB** | 1,219 → 307 KB | 25 → 15 | 143 → 121 ms | 0.005 → 0.000 |
| request SQL | 779 → **145 KB** | 1,331 → 420 KB | 29 → 19 | 210 → 190 ms | 0.013 → 0.000 |
| profiling | 809 → **175 KB** | 1,187 → 405 KB | 30 → 22 | 146 → 118 ms | 0.028 → 0.001 |
| profile detail | 2,446 → **1,812 KB** | 2,852 → 1,975 KB | 29 → 19 | 131 → 107 ms | 0.044 → 0.000 |
| settings | 728 → **94 KB** | 1,052 → 260 KB | 20 → 11 | 109 → 81 ms | 0.010 → 0.000 |

- JavaScript drops 62 to 87% on every page except the profile pages, which
  drop 26%: they still carry the 1.8 MB graph library. Loading it only when a
  graph is opened is part of the Profiling phase.
- htmx is vendored but not loaded yet; it arrives with the Requests phase, so
  these JS figures do not include its 52 KB.
- HTML grows by about 14 KB per page (roughly 4 KB gzipped): the inline icon
  sprite that replaces 384 KB of icon JavaScript.
- Request counts fall by 8 to 10 per page; the rest are per-page CSS and JS
  files that go away as each page is rebuilt.
- The JS target is revised to under 100 KB uncompressed: htmx alone is 52 KB
  uncompressed (16 KB gzipped), and the earlier 60 KB figure assumed gzip.
- Summary is still 617 ms because its time is server-side aggregation, fixed
  in the Summary phase.

## Phase 2: requests list and request detail, recorded 2026-10-25

Server-side changes: the list joins each row's response and computes DB time
as a subquery instead of two extra queries per row; the path filter's
checkbox per recorded path is replaced by a search box; jQuery loads only on
pages whose scripts still need it. Filters, sort and paging update the list
through htmx instead of reloading the page. CPU 4×, 5,000 requests:

| Page | DB queries | Render | HTML, 200 / 5k requests | JS | Requests | Load |
|---|---:|---:|---:|---:|---:|---:|
| requests | 59 → **13** | 22 → 10 ms | 100 / 697 → **51 / 51 KB** | 822 → **65 KB** | 29 → 13 | 180 → 120 ms |
| request detail | 6 → **6** | 4 → 5 ms | 11 / 11 → **31 / 31 KB** | 762 → **44 KB** | 25 → 15 | 143 → 118 ms |
| settings | 0 → **0** | 0 → 0 ms | 25 / 25 → **28 / 28 KB** | 728 → **10 KB** | 20 → 10 | 109 → 67 ms |

- **Changing a filter now takes 62 ms** (click to swapped results, CPU 4×),
  against a 180 ms full reload before. Target was under 100 ms.
- **The requests page HTML no longer grows with data**: 51 KB at both 200
  and 5,000 requests, against 100 KB and 697 KB before.
- **JS is under the 100 KB target** on the requests list (65 KB, of which
  htmx is 52 KB), request detail (44 KB) and settings (10 KB).
- The request detail page stays at 6 queries: the overview's endpoint median
  adds one, and the header no longer runs its own DB-time aggregate. Repeated
  query analysis and the likely fix reuse the queries the page already loads.
- HTTP requests are 13 to 15 per page against a target of 8: four font files,
  two favicons and separate small scripts. Bundling the scripts is left for a
  later pass.

## Phase 3: SQL patterns and Hotspots, recorded 2026-10-25

New pages that group every recorded query by shape and by the line of app code
that ran it. Migration 0010 adds `SQLQuery.pattern_hash` and
`SQLQuery.code_location`, filled on save, with composite indexes on
(column, request). Without them the same pages took about 1 s at 5,000
requests (76,000 queries were normalised in Python on every view).

| Page | DB queries | Render, 200 req | Render, 5k req | HTML | JS | Load, CPU 4× |
|---|---:|---:|---:|---:|---:|---:|
| SQL patterns | 5 | 4 ms | **82 ms** | 37 KB | 62 KB | 181 ms |
| SQL, pattern open | 13 | 7 ms | **109 ms** | 56 KB | 62 KB | 228 ms |
| Hotspots | 5 | 3 ms | **82 ms** | 25 KB | 62 KB | 163 ms |
| Hotspots, line open | 13 | 7 ms | **137 ms** | 36 KB | 62 KB | 238 ms |

- All four render under the 150 ms target at 5,000 requests; the open line
  panel is the slowest at 137 ms median.
- "Repeats inside one request" is a two-level GROUP BY read straight from the
  (column, request) index: 8 to 9 ms, against 83 to 89 ms without it.
- The backfill in migration 0010 took about 10 s for 76,000 existing queries
  on SQLite.
- No aggregate touches the SQL text column, so the pages keep working on
  Oracle, where that column is a LOB that cannot be grouped.

## v1.7.0: the finished redesign, recorded 2026-10-26

All phases together: Profiling, Compare, Settings, the command palette, the
request side panel and the sidebar with counts and quick views. Same machine
and dataset as the baseline (5,000 requests, 75,973 queries, 4,885 profiles).

Server renders now clear the cache before every render, so the "cold" column
includes the sidebar counts, which are otherwise cached for 30 s. "Warm" is
the same page with the cache kept (`--cached`), which is what a second page
view within 30 s costs. Browser figures are at CPU 4×.

| Page | Render, 200 req | Render, 5k cold | Render, 5k warm | DB queries, cold / warm | HTML, 5k | JS | Requests | Load | CLS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| summary | 21 → 15 ms | 465 → **59 ms** | 36 ms | 55 → 14 / 4 | 31 → 147 KB | 1,026 → **71 KB** | 22 → 13 | 613 → **154 ms** | 0.016 → 0.002 |
| requests | 12 → 8 ms | 22 → 41 ms | 19 ms | 59 → 27 / 17 | 697 → **53 KB** | 822 → **78 KB** | 29 → 14 | 180 → 130 ms | 0.038 → 0.000 |
| requests, sorted by time | 14 → 12 ms | 29 → 53 ms | 32 ms | 63 → 31 / 21 | 701 → 54 KB | 822 → 78 KB | 29 → 14 | 193 → 143 ms | 0.031 → 0.000 |
| request detail | 4 → 7 ms | 4 → 29 ms | 6 ms | 6 → 17 / 7 | 11 → 25 KB | 762 → 54 KB | 25 → 15 | 143 → 110 ms | 0.005 → 0.000 |
| request SQL | 62 → 35 ms | 71 → 61 ms | 39 ms | 7 → 16 / 6 | 84 → 98 KB | 779 → 20 KB | 29 → 12 | 210 → 139 ms | 0.013 → 0.000 |
| request SQL detail | 2 → 4 ms | 1 → 25 ms | 2 ms | 4 → 14 / 4 | 10 → 22 KB | 763 → 54 KB | 29 → 15 | 125 → 92 ms | 0.020 → 0.000 |
| request profiling | 2 → 4 ms | 2 → 25 ms | 2 ms | 8 → 20 / 10 | 15 → 18 KB | 809 → 71 KB | 30 → 13 | 128 → 75 ms | 0.001 → 0.000 |
| profiling | 8 → 12 ms | 9 → 70 ms | 48 ms | 31 → 20 / 10 | 45 → 132 KB | 809 → 71 KB | 30 → 13 | 146 → 160 ms | 0.028 → 0.004 |
| profile detail | 1 → 3 ms | 1 → 24 ms | 2 ms | 6 → 16 / 6 | 8 → 17 KB | 2,446 → **20 KB** | 29 → 12 | 131 → 65 ms | 0.044 → 0.000 |
| cProfile | 1 → 3 ms | 1 → 24 ms | 1 ms | 3 → 13 / 3 | 7 → 17 KB | 2,446 → **20 KB** | 29 → 12 | 114 → 68 ms | 0.002 → 0.000 |
| settings | 0 → 3 ms | 0 → 25 ms | 2 ms | 0 → 15 / 5 | 25 → 29 KB | 728 → 24 KB | 20 → 13 | 109 → 103 ms | 0.010 → 0.001 |
| SQL patterns | 8 ms | 116 ms | 94 ms | 16 / 6 | 34 KB | 71 KB | 13 | 192 ms | 0.004 |
| SQL, pattern open | 11 ms | 146 ms | 127 ms | 24 / 14 | 52 KB | 71 KB | 13 | 235 ms | 0.002 |
| Hotspots | 5 ms | 108 ms | 83 ms | 15 / 5 | 21 KB | 71 KB | 13 | 161 ms | 0.004 |
| Hotspots, line open | 9 ms | 156 ms | 133 ms | 23 / 13 | 33 KB | 71 KB | 13 | 232 ms | 0.002 |
| Compare, two time ranges | 9 ms | 74 ms | 52 ms | 37 / 27 | 40 KB | 20 KB | 12 | 159 ms | 0.000 |
| Compare, pick an endpoint | 5 ms | 29 ms | 7 ms | 31 / 21 | 22 KB | 71 KB | 12 | 79 ms | 0.000 |
| Compare, two requests | 5 ms | 27 ms | 5 ms | 29 / 19 | 25 KB | 20 KB | 12 | 95 ms | 0.000 |
| request panel (htmx fragment) | 7 ms | 8 ms | 8 ms | 8 / 8 | 61 KB | | | | |

Interactions on the requests list, CPU 4×: **a filter change takes 70 ms** and
**opening a request in the side panel takes 44 ms**, against a 180 ms full page
load for either in the old UI.

### Against the targets

| Metric | Old UI | Target | v1.7.0 |
|---|---|---|---|
| JS per page (except profile graph) | 728 KB to 1,026 KB | under 100 KB | **20 to 78 KB**, met |
| HTTP requests per page | 20 to 30 | under 8 | 12 to 15, not met |
| Requests HTML at 5k requests | 697 KB | under 120 KB, independent of dataset size | **53 KB** at 200 and 5,000, met |
| Summary render at 5k requests | 465 ms | under 150 ms | **59 ms** cold, met |
| DB queries on summary / requests | 55 / 59 | under 15 each | 14 / 27 cold, 4 / 17 warm: met for summary only |
| Filter, sort or page change | full reload (180 ms) | partial update, under 100 ms | **70 ms**, met |
| CLS | up to 0.044 | under 0.05 | 0.004 at most, met |

### What changed since Phase 3, and what it costs

- **The sidebar counts cost about 21 ms and 9 queries** whenever their 30 s
  cache is cold, on every page. That is why small pages such as request detail
  went from 4 ms to 29 ms cold. With a warm cache they are back to 2 to 6 ms.
  The request panel avoids the cost entirely because it renders no sidebar.
- **The requests list does more per render than in Phase 2**: the trend line,
  per-method and per-status counts, and the N+1 count. The N+1 request ids are
  cached for 30 s (keyed by the newest query, so new requests still show at
  once), which took the warm render from 33 ms to 19 ms. Phase 2 measured 10 ms.
- **The profile pages no longer load the 2.4 MB graph library** on every visit:
  JS is 20 KB, and the graph loads only when opened.
- **Profiling renders the top 100 blocks** instead of 200, halving its HTML from
  247 KB to 132 KB. It does not grow with data; search and sort reach the rest.
- **Summary HTML is 147 KB at 5,000 requests**: the charts are inline SVG with
  a link per dot, capped at 400 dots.
- **Opening a pattern or a code line takes 146 to 156 ms cold**, just over the
  150 ms used for the Phase 3 pages, because the sidebar counts were added.
- **One layout shift was found and fixed**: on the Compare endpoint picker,
  "Compare newest two →" wrapped in the fallback font and unwrapped when the
  web font loaded, moving every row (CLS 0.127, now 0.000).
- **HTTP requests stay at 12 to 15** against a target of 8: four font files,
  two favicons and separate small scripts. Bundling them is still open.
