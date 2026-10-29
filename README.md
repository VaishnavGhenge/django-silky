# django-silky

[![PyPI](https://img.shields.io/pypi/v/django-silky.svg)](https://pypi.org/project/django-silky/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-silky.svg)](https://pypi.org/project/django-silky/)
[![Supported Django versions](https://img.shields.io/pypi/djversions/django-silky.svg)](https://pypi.org/project/django-silky/)
[![Tests](https://github.com/VaishnavGhenge/django-silky/actions/workflows/test.yml/badge.svg)](https://github.com/VaishnavGhenge/django-silky/actions/workflows/test.yml)
[![Downloads/month](https://img.shields.io/pypi/dm/django-silky.svg?label=downloads%2Fmonth)](https://pypi.org/project/django-silky/)
[![Downloads total](https://static.pepy.tech/badge/django-silky)](https://pepy.tech/project/django-silky)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**django-silky** is a modernized-UI fork of [django-silk](https://github.com/jazzband/django-silk), a live profiling and inspection tool for the Django framework.

It records the same data as django-silk (requests and responses, SQL queries, code profiles, dynamic profiling) and adds a rebuilt interface aimed at one question: what should I fix first? It groups queries by shape and by the line of your code that ran them, flags N+1 patterns with a likely fix, compares two requests or two time ranges, and filters without reloading the page. JavaScript per page is 20 to 78 KB, against 0.7 to 2.4 MB in django-silk ([benchmarks](benchmarks/README.md)).

<img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/demo.gif" alt="Opening an N+1 suspect: the request panel names the calling line and suggests select_related, then the SQL and Hotspots pages" width="840"/>

---

## What's different from django-silk?

| | django-silk | django-silky |
|---|---|---|
| Requests list | Slide-out filter form, full page reload per change | Filter chips with counts, top bar search, updates in place; requests open in a side panel |
| Request detail | Tables of fields | Overview with SQL versus Python time, N+1 and duplicate detection, a likely fix at the calling line, copyable curl and query-count tests |
| SQL across requests | Per request only | **SQL** page: every query grouped by shape, with p95, DB time per table and the requests that run it |
| Where queries come from | Stack trace per query | **Hotspots** page: lines of your code ranked by the DB time they cause, loops flagged |
| Summary | Counts and top-N tables | Latency over time, endpoints to fix first with the reason, scatter and heatmap per endpoint |
| Profiling | List of profiles | Grouped into code blocks; cProfile as a sortable function list; call graph loads on demand |
| Comparison | None | **Compare** two requests, or two time ranges such as before and after a deploy |
| Settings | Clear data | Theme and accent, editor links with path mapping, slow and N+1 thresholds, recording config with risk notes |
| Keyboard | None | Command palette (Ctrl/Cmd+K), `/` to search, `j`/`k` through requests, `g` + letter between pages |
| Assets | jQuery, Font Awesome from a CDN | No jQuery or CDN; htmx and an inline icon sprite; fonts ship with the package |

---

## Screenshots

<table>
<tr>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/summary.png" alt="Summary page" width="420"/><br/><sub><b>Summary</b>: latency over time, the endpoints to fix first and why, status codes, and where the time goes</sub></td>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/request-panel.png" alt="Requests list with a request open in the side panel" width="420"/><br/><sub><b>Request panel</b>: opens beside the list; duplicate query found with the calling line and a likely fix</sub></td>
</tr>
<tr>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/sql-patterns.png" alt="SQL page with a pattern open" width="420"/><br/><sub><b>SQL</b>: every query grouped by shape, DB time per table, and an N+1 pattern with the line that runs it</sub></td>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/hotspots.png" alt="Hotspots page with a code line open" width="420"/><br/><sub><b>Hotspots</b>: lines of app code ranked by the DB time they cause</sub></td>
</tr>
<tr>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/requests.png" alt="Requests list" width="420"/><br/><sub><b>Requests</b>: headline numbers, filter chips with counts, N+1 flags per row</sub></td>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/profiling.png" alt="Profiling page with a code block open" width="420"/><br/><sub><b>Profiling</b>: profiles grouped into code blocks, with the spread and the slowest runs</sub></td>
</tr>
<tr>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/compare.png" alt="Compare two time ranges" width="420"/><br/><sub><b>Compare</b>: two time ranges, with the verdict and per-endpoint changes</sub></td>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/settings.png" alt="Settings page" width="420"/><br/><sub><b>Settings</b>: editor links with path mapping, thresholds, appearance and recording config</sub></td>
</tr>
<tr>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/summary-dark.png" alt="Summary page in dark theme" width="420"/><br/><sub><b>Dark theme</b>: system, light or dark, with four accents</sub></td>
<td><img src="https://raw.githubusercontent.com/VaishnavGhenge/django-silky/master/screenshots/command-palette.png" alt="Command palette over the requests list" width="420"/><br/><sub><b>Command palette</b>: Ctrl/Cmd+K to jump anywhere</sub></td>
</tr>
</table>

---

## Migrating from django-silk

`django-silky` is a drop-in replacement: same app label (`silk`), upstream's
migrations unchanged, and your recorded data is kept. It adds one migration
of its own (0010, two columns and two indexes on `silk_sqlquery`), so run
`migrate` once after switching.

```bash
pip uninstall django-silk
pip install django-silky
python manage.py migrate silk
```

For version compatibility and rollback steps see
**[MIGRATING.md](MIGRATING.md)**.

---

## Requirements

* Django 5.2, 6.0, 6.1
* Python 3.10, 3.11, 3.12, 3.13, 3.14, 3.15

---

## Installation

```bash
pip install django-silky
```

With optional request body formatting:

```bash
pip install django-silky[formatting]
```

### settings.py

```python
MIDDLEWARE = [
    ...
    'silk.middleware.SilkyMiddleware',
    ...
]

TEMPLATES = [{
    ...
    'OPTIONS': {
        'context_processors': [
            ...
            'django.template.context_processors.request',
        ],
    },
}]

INSTALLED_APPS = [
    ...
    'silk',
]
```

> **Middleware order:** Any middleware placed *before* `SilkyMiddleware` that returns a response without calling `get_response` will prevent Silk from running. If you use `django.middleware.gzip.GZipMiddleware`, place it **before** `SilkyMiddleware`.

### urls.py

```python
from django.urls import include, path

urlpatterns += [
    path('silk/', include('silk.urls', namespace='silk')),
]
```

### Migrate and collect static

```bash
python manage.py migrate
python manage.py collectstatic
```

The UI is now available at `/silk/`.

---

## Features

### Request Inspection

Silk's middleware records every HTTP request and response: method, status code, path, timing, SQL query count, headers and bodies. The Requests page filters them with chips (method, status class, slow, N+1, time range, query count) and a search box, and opens each request in a side panel beside the list. Each request shows how its time splits between SQL and Python, how it compares with the endpoint's usual time and query count, and any repeated queries, with whether they are an N+1 or a plain duplicate and the likely fix.

### SQL Inspection

Every SQL query is captured with its execution time and a stack trace, so you can see where in your code it ran. Beyond the per-request view:

- **SQL** groups every recorded query by shape (values replaced), with calls, requests, total, average and p95 time, DB time per table, and the requests that run each pattern.
- **Hotspots** ranks the lines of your application code by the database time they cause, and flags lines that run queries inside a loop.

Source locations link to your editor (VS Code, Cursor, PyCharm or Sublime Text), with a path mapping for code that runs in Docker or a VM.

### Compare

Compare two requests to the same endpoint (time, queries and a pattern-by-pattern diff), or two time ranges such as before and after a deploy, with the change per endpoint and per query pattern.

### Code Profiling

#### Decorator / context manager

```python
from silk.profiling.profiler import silk_profile

@silk_profile(name='View Blog Post')
def post(request, post_id):
    p = Post.objects.get(pk=post_id)
    return render(request, 'post.html', {'post': p})
```

```python
def post(request, post_id):
    with silk_profile(name='View Blog Post #%d' % post_id):
        p = Post.objects.get(pk=post_id)
        return render(request, 'post.html', {'post': p})
```

#### cProfile integration

```python
SILKY_PYTHON_PROFILER = True
SILKY_PYTHON_PROFILER_BINARY = True  # also save .prof files
```

When enabled, each request's cProfile output is shown as a sortable function list, and a call graph coloured by time loads on request.

#### Dynamic profiling

Profile third-party code without touching its source:

```python
SILKY_DYNAMIC_PROFILING = [{
    'module': 'path.to.module',
    'function': 'MyClass.bar',
}]
```

### Code Generation

Silk generates a `curl` command and a Django test-client snippet for every request, making it easy to replay a captured request from the terminal or a unit test.

---

## Configuration

### Authentication

**Silk is locked down by default.** Unauthenticated or non-staff requests to `/silk/` return **404 Not Found** — as if the app weren't mounted — so an accidental production deployment can't leak profiling data.

```python
# To expose the UI publicly (internal dev-only, not recommended):
SILKY_AUTHENTICATION = False
SILKY_AUTHORISATION = False

# To change who is allowed in (default: user.is_staff):
SILKY_PERMISSIONS = lambda user: user.is_superuser
```

### Request / response body limits

```python
SILKY_MAX_REQUEST_BODY_SIZE = -1    # -1 = no limit
SILKY_MAX_RESPONSE_BODY_SIZE = 1024 # bytes; larger bodies are discarded
```

### Sampling (high-traffic sites)

```python
SILKY_INTERCEPT_PERCENT = 50  # record only 50 % of requests
# or
SILKY_INTERCEPT_FUNC = lambda request: 'profile' in request.session
```

To keep only requests whose response matched given status codes (for example, server errors only):

```python
SILKY_INTERCEPT_STATUS_CODES = {500, 501}  # default None records every status
```

The status code is only known once the response is ready, so Silk still records each request
and then discards it if the status code is not in the set.

To stop recording particular paths entirely:

```python
SILKY_IGNORE_PATHS = ['/healthz', '/readyz']
```

Entries are matched exactly against `request.path_info`, i.e. without any `SCRIPT_NAME` prefix.
Silk's own views are always ignored.

### Garbage collection

```python
SILKY_MAX_RECORDED_REQUESTS = 10_000
SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT = 10  # GC runs on 10 % of requests
```

#### Retention mode

By default Silk keeps the newest `SILKY_MAX_RECORDED_REQUESTS` rows (count-based).
To keep a rolling time window instead — useful for spotting patterns across days —
switch the mode and set a maximum age in minutes:

```python
SILKY_GARBAGE_COLLECT_MODE = 'time'      # 'count' (default) | 'time' | 'both'
SILKY_MAX_RECORDED_TIME = 60 * 24 * 7    # minutes; keep the last 7 days
```

`'both'` applies the count cap and the age window together (whichever trims more).
The count default is unchanged, so existing setups keep their current behaviour.

Trigger manually (e.g. from a cron job):

```bash
python manage.py silk_request_garbage_collect
# override per run:
python manage.py silk_request_garbage_collect --mode time --max-time 10080
```

Clear all data immediately:

```bash
python manage.py silk_clear_request_log
```

### Query analysis

```python
SILKY_ANALYZE_QUERIES = True
SILKY_EXPLAIN_FLAGS = {'format': 'JSON', 'costs': True}
```

> **Warning:** `EXPLAIN ANALYZE` on PostgreSQL actually executes the query, which may cause unintended side effects. Use with caution.

### Meta-profiling

```python
SILKY_META = True  # shows how long Silk itself takes per request
```

### Sensitive data masking

```python
# Default set — case insensitive
SILKY_SENSITIVE_KEYS = {'username', 'api', 'token', 'key', 'secret', 'password', 'signature'}
```

### Custom profiler storage

```python
# Django >= 4.2
STORAGES = {
    'SILKY_STORAGE': {
        'BACKEND': 'path.to.StorageClass',
    },
}

SILKY_PYTHON_PROFILER_RESULT_PATH = '/path/to/profiles/'
```

---

## Development

```bash
git clone https://github.com/VaishnavGhenge/django-silky.git
cd django-silky
python -m venv .venv && source .venv/bin/activate
pip install -e ".[formatting]"
pip install --group test  # pip >= 25.1

# Run the example project
DB_ENGINE=sqlite3 python project/manage.py migrate
# Replace old profiling records with a week of synthetic shop traffic
DB_ENGINE=sqlite3 python project/manage.py silk_seed --clear --requests 1000 --days 7 --seed 42
DB_ENGINE=sqlite3 python project/manage.py runserver
# Visit http://127.0.0.1:8000/silk/  (login: admin / admin)

# Watch SCSS while editing UI (Node Version 24.15)
pnpm install || npm install
npm run watch

# For CSS Build
npm run build

# Run tests
DB_ENGINE=sqlite3 python -m pytest project/tests/ -q
```

`silk_seed` simulates a week of traffic for a fictional Django kitchenware shop: a storefront
API, cart and checkout, logins, the Django admin, payment webhooks and a staff sales report.
Traffic follows a daily rhythm with an evening peak. The data includes the problems Silk is
meant to find: an N+1 on the order list, a 100-row admin changelist N+1, an exchange rate
fetched once per product variant, slow `LIKE` searches, a multi-second report with cProfile
output, and occasional 4xx and 500 responses (gateway timeouts, statement timeouts, a webhook
race). SQL and profiles stay within their request's timeline, and recorded query counts match
the stored queries. The application paths in tracebacks are fictional, so source links do not
open. `--clear` deletes only Silk profiling records. With SQLite, the default database
file is named `postgres`; set `DB_NAME` to use a different file.

---

## Credits

django-silky is a fork of [django-silk](https://github.com/jazzband/django-silk), originally created by [Michael Ford](https://github.com/mtford90) and maintained by [Jazzband](https://jazzband.co/). All core profiling functionality comes from the upstream project; this fork focuses solely on UI improvements.

---

## License

MIT — same as the upstream [django-silk](https://github.com/jazzband/django-silk).
