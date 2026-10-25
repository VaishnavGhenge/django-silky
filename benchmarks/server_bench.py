"""Server-side benchmark for the Silk UI.

Seeds a deterministic dataset into its own SQLite file, then renders every Silk
page through Django's test client and records render time, DB query count and
HTML size per page. Run it before and after UI changes and compare the JSON.

    .venv/bin/python benchmarks/server_bench.py --requests 200 --label baseline
    .venv/bin/python benchmarks/server_bench.py --requests 5000 --label baseline

Results are written to benchmarks/results/<label>-server-<requests>.json.
"""

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / '.data'
RESULTS = Path(__file__).resolve().parent / 'results'


def setup_django(db_path):
    os.environ['DB_ENGINE'] = 'sqlite3'
    os.environ['DB_NAME'] = str(db_path)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')
    sys.path.insert(0, str(ROOT / 'project'))
    sys.path.insert(0, str(ROOT))
    import django
    django.setup()


def ensure_dataset(n_requests):
    """Migrate and seed once per dataset size; reuse the file on later runs."""
    from django.core.management import call_command

    from silk.models import Request
    call_command('migrate', verbosity=0)
    if Request.objects.count() != n_requests:
        random.seed(42)  # same data every time, so runs are comparable
        call_command('silk_seed', requests=n_requests, days=14, clear=True, stdout=open(os.devnull, 'w'))


def pages():
    """One URL per Silk page, using real ids from the seeded data."""
    from django.urls import reverse

    from silk.models import Profile, Request, SQLQuery
    busiest = Request.objects.order_by('-num_sql_queries').first() if hasattr(Request, 'num_sql_queries') else None
    req = busiest or max(Request.objects.all()[:500], key=lambda r: r.queries.count())
    sql = SQLQuery.objects.filter(request=req).first()
    prof = Profile.objects.filter(request__isnull=False).first()
    prof_req = prof.request if prof else req
    cprof = Request.objects.exclude(pyprofile='').first()
    urls = {
        'summary': reverse('silk:summary'),
        'requests': reverse('silk:requests'),
        'requests_sorted_time': reverse('silk:requests') + '?order_by=time_taken',
        'request_detail': reverse('silk:request_detail', args=[req.id]),
        'request_sql': reverse('silk:request_sql', args=[req.id]),
        'request_sql_detail': reverse('silk:request_sql_detail', args=[req.id, sql.id]) if sql else None,
        'request_profiling': reverse('silk:request_profiling', args=[prof_req.id]),
        'profiling': reverse('silk:profiling'),
        'profile_detail': reverse('silk:profile_detail', args=[prof.id]) if prof else None,
        'cprofile': reverse('silk:cprofile', args=[cprof.id]) if cprof else None,
        'cleardb': reverse('silk:cleardb'),
    }
    # Pages added by the redesign (absent from the old UI, so only measured when they exist).
    try:
        pattern = SQLQuery.objects.order_by('-time_taken').values_list('pattern_hash', flat=True).first()
        location = SQLQuery.objects.exclude(code_location='').values_list('code_location', flat=True).first()
        urls['sql_patterns'] = reverse('silk:sql')
        urls['sql_pattern_panel'] = reverse('silk:sql') + f'?p={pattern}'
        urls['hotspots'] = reverse('silk:hotspots')
        urls['hotspot_panel'] = reverse('silk:hotspots') + '?' + urlencode({'loc': location})
    except Exception:  # NoReverseMatch / missing columns on the old UI
        pass
    return {k: v for k, v in urls.items() if v}


def measure(client, url, runs):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    client.get(url)  # warm caches and template loading
    times, queries, size, status = [], 0, 0, None
    for _ in range(runs):
        with CaptureQueriesContext(connection) as ctx:
            start = time.perf_counter()
            resp = client.get(url)
            times.append((time.perf_counter() - start) * 1000)
        queries, size, status = len(ctx.captured_queries), len(resp.content), resp.status_code
    times.sort()
    return {
        'url': url,
        'status': status,
        'median_ms': round(statistics.median(times), 1),
        'p90_ms': round(times[int(len(times) * 0.9) - 1 if len(times) >= 10 else -1], 1),
        'queries': queries,
        'html_kb': round(size / 1024, 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--requests', type=int, default=200, help='dataset size (recorded requests)')
    ap.add_argument('--runs', type=int, default=10, help='timed renders per page')
    ap.add_argument('--label', default='run', help='name for the results file')
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    setup_django(DATA / f'bench-{args.requests}.sqlite3')
    ensure_dataset(args.requests)

    from django.conf import settings
    from django.test import Client

    from silk.models import Profile, Request, SQLQuery
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
    client = Client()
    out = {
        'label': args.label,
        'dataset': {'requests': Request.objects.count(), 'queries': SQLQuery.objects.count(), 'profiles': Profile.objects.count()},
        'runs': args.runs,
        'pages': {name: measure(client, url, args.runs) for name, url in pages().items()},
    }
    bad = {name: m['status'] for name, m in out['pages'].items() if m['status'] != 200}
    if bad:
        sys.exit(f'pages did not render (status codes): {bad}')
    path = RESULTS / f'{args.label}-server-{args.requests}.json'
    path.write_text(json.dumps(out, indent=2) + '\n')

    print(f"{'page':24} {'median':>9} {'p90':>9} {'queries':>8} {'html':>9}")
    for name, m in out['pages'].items():
        print(f"{name:24} {m['median_ms']:>7} ms {m['p90_ms']:>7} ms {m['queries']:>8} {m['html_kb']:>6} KB")
    print(f'\nwrote {path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
