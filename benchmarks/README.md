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
