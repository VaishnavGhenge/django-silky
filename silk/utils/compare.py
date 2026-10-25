"""Data for the Compare pages: two requests side by side, or two time ranges.

An endpoint is a request's view_name, or its path when the view has no name,
matching the Summary page. Query patterns are compared by pattern_hash, with
one sample query per pattern for display.
"""
from datetime import timedelta

from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from silk.utils.fmt import fmt_ms
from silk.utils.sql_patterns import sql_table, sql_type
from silk.utils.summary_data import REPEAT_MIN, _pct, repeating_request_ids

MAX_ROWS = 20000      # requests read per side
ACTIVITY_BUCKETS = 72
PATTERNS_SHOWN = 12
ENDPOINTS_IN_MENU = 100


def endpoint_key(view_name, path):
    return view_name or path


def endpoint_q(ep, prefix=''):
    """Q matching requests of endpoint `ep` (a view name, or a path for unnamed views)."""
    return Q(**{prefix + 'view_name': ep}) | Q(**{prefix + 'view_name': '', prefix + 'path': ep})


def _samples(ids):
    from silk.models import SQLQuery
    return dict(SQLQuery.objects.filter(pk__in=ids).values_list('pk', 'query'))


def _pattern_rows(qs):
    """{pattern_hash: {'n', 'ms', 'sample'}} for the SQLQuery queryset `qs`."""
    return {r['pattern_hash']: r for r in qs.exclude(pattern_hash='').values('pattern_hash').annotate(
        n=Count('id'), ms=Sum('time_taken'), sample=Min('id'))}


def _with_sql(rows):
    samples = _samples([r['sample'] for r in rows])
    for r in rows:
        sql = samples.get(r['sample'], '')
        r.update(sql=sql, type=sql_type(sql), table=sql_table(sql))
    return rows


# ── Two requests ──────────────────────────────────────────────────

def siblings(silk_request):
    """(position, count, older, newer) of a request among requests to the same endpoint."""
    from silk.models import Request
    same = Request.objects.filter(endpoint_q(endpoint_key(silk_request.view_name, silk_request.path)))
    older = same.filter(start_time__lt=silk_request.start_time).order_by('-start_time')
    newer = same.filter(start_time__gt=silk_request.start_time).order_by('start_time')
    position = older.count() + 1
    return {'position': position, 'count': same.count(),
            'older': older.values_list('pk', flat=True).first(), 'newer': newer.values_list('pk', flat=True).first()}


def _request_side(r):
    from silk.models import SQLQuery
    queries = SQLQuery.objects.filter(request=r)
    patterns = _pattern_rows(queries)
    db = queries.aggregate(ms=Sum('time_taken'))['ms'] or 0
    return {
        'request': r, 'sib': siblings(r), 'patterns': patterns, 'db': db,
        'repeated': sum(p['n'] for p in patterns.values() if p['n'] >= REPEAT_MIN),
    }


def _change(a, b, lower_is_better=True, fmt='ms'):
    d = (b or 0) - (a or 0)
    if abs(d) < 1e-9:
        return {'text': 'no change', 'cls': ''}
    good = d < 0 if lower_is_better else d > 0
    pct = f' ({"+" if d > 0 else ""}{d / a * 100:.0f}%)' if a else ''
    value = fmt_ms(abs(d)) if fmt == 'ms' else f'{abs(d):.1f}' if fmt == 'f1' else f'{abs(d):.1f}%' if fmt == 'pct' else f'{abs(d):.0f}'
    return {'text': ('+' if d > 0 else '−') + value + pct, 'cls': 'is-good' if good else 'is-bad'}


def compare_requests(a, b):
    A, B = _request_side(a), _request_side(b)
    ta, tb = a.time_taken or 0, b.time_taken or 0
    time_pct = abs(tb - ta) / ta * 100 if ta else 0
    qd = b.num_sql_queries - a.num_sql_queries
    if time_pct < 5:
        kind, headline = 'neutral', 'B takes about the same time'
    else:
        kind = 'ok' if tb < ta else 'bad'
        headline = f'B is {time_pct:.0f}% {"faster" if tb < ta else "slower"}'
    queries = f'and runs {abs(qd)} {"fewer" if qd < 0 else "more"} queries' if qd else 'with the same number of queries'

    diff = []
    for h in set(A['patterns']) | set(B['patterns']):
        pa, pb = A['patterns'].get(h), B['patterns'].get(h)
        na, nb = (pa or {}).get('n', 0), (pb or {}).get('n', 0)
        kind_ = 'new' if not na else 'gone' if not nb else 'more' if nb > na else 'fewer' if nb < na else 'same'
        ams, bms = (pa or {}).get('ms') or 0, (pb or {}).get('ms') or 0
        diff.append({'pattern_hash': h, 'a': na, 'b': nb, 'ams': ams, 'bms': bms, 'kind': kind_,
                     'sample': (pa or pb)['sample'], 'dms': bms - ams})
    diff.sort(key=lambda d: -abs(d['dms']))
    _with_sql(diff)

    def row(label, va, vb, fmt):
        return {'label': label, 'a': va, 'b': vb, 'fmt': fmt, 'change': _change(va, vb, True, fmt)}

    return {
        'A': A, 'B': B,
        'verdict': {'kind': kind, 'headline': headline, 'detail': f'({fmt_ms(ta)} → {fmt_ms(tb)}) {queries}.'},
        'metrics': [
            row('Total time', ta, tb, 'ms'),
            row('DB time', A['db'], B['db'], 'ms'),
            row('Queries', a.num_sql_queries, b.num_sql_queries, 'int'),
            row('Queries in repeating patterns', A['repeated'], B['repeated'], 'int'),
            row('Distinct patterns', len(A['patterns']), len(B['patterns']), 'int'),
        ],
        'diff': diff,
        'changed': [d for d in diff if d['kind'] != 'same'],
    }


def endpoints_with_history(q=''):
    """Endpoints with at least two requests, busiest first, for picking a pair."""
    from silk.models import Request
    groups = Request.objects.order_by().values('view_name', 'path').annotate(n=Count('id'))
    if q:
        groups = groups.filter(Q(view_name__icontains=q) | Q(path__icontains=q))
    by = {}
    for g in groups:
        key = endpoint_key(g['view_name'], g['path'])
        by[key] = by.get(key, 0) + g['n']
    eps = sorted(((k, n) for k, n in by.items() if n >= 2), key=lambda e: -e[1])[:200]
    out = []
    for key, n in eps:
        last_two = list(Request.objects.filter(endpoint_q(key)).order_by('-start_time').values_list('pk', flat=True)[:2])
        out.append({'key': key, 'count': n, 'a': last_two[1], 'b': last_two[0]})
    return out


# ── Two time ranges ───────────────────────────────────────────────

def local(dt):
    return timezone.localtime(dt) if timezone.is_aware(dt) else dt


def _range_q(rng, ep, prefix=''):
    q = Q(**{prefix + 'start_time__gte': rng[0], prefix + 'start_time__lt': rng[1]})
    return q & endpoint_q(ep, prefix) if ep else q


def presets():
    """Preset range pairs anchored on the newest recorded request, so old data still compares."""
    from silk.models import Request
    newest = Request.objects.order_by('-start_time').values_list('start_time', flat=True).first()
    if not newest:
        return []
    end = newest + timedelta(minutes=1)
    hour, day = timedelta(hours=1), timedelta(days=1)
    out = [
        {'id': '1h', 'label': 'Last hour vs the hour before', 'a': (end - 2 * hour, end - hour), 'b': (end - hour, end)},
        {'id': '24h', 'label': 'Last 24 h vs the 24 h before', 'a': (end - 2 * day, end - day), 'b': (end - day, end)},
        {'id': '7d', 'label': 'Last 7 days vs the 7 before', 'a': (end - 14 * day, end - 7 * day), 'b': (end - 7 * day, end)},
    ]
    d2 = local(newest).replace(hour=0, minute=0, second=0, microsecond=0)
    prev = Request.objects.filter(start_time__lt=d2).order_by('-start_time').values_list('start_time', flat=True).first()
    if prev:
        d1 = local(prev).replace(hour=0, minute=0, second=0, microsecond=0)
        out.insert(0, {'id': 'days', 'label': 'Last active day vs the one before', 'a': (d1, d1 + day), 'b': (d2, d2 + day)})
    for p in out:
        p['na'] = Request.objects.filter(_range_q(p['a'], '')).count()
        p['nb'] = Request.objects.filter(_range_q(p['b'], '')).count()
    return out


def default_ranges(preset_list):
    for p in preset_list:
        if p['na'] and p['nb']:
            return p
    return preset_list[0] if preset_list else None


def _rows(rng, ep):
    from silk.models import Request
    qs = Request.objects.filter(_range_q(rng, ep), time_taken__isnull=False).order_by('-start_time')
    return list(qs.values_list('id', 'time_taken', 'num_sql_queries', 'view_name', 'path', 'response__status_code')[:MAX_ROWS])


def _agg(rows, n1_ids, db_ms):
    n = len(rows) or 1
    ms = sorted(r[1] or 0 for r in rows)
    return {
        'n': len(rows), 'p50': _pct(ms, .5), 'p95': _pct(ms, .95),
        'q': sum(r[2] or 0 for r in rows) / n,
        'db': db_ms / n,
        'err': sum(1 for r in rows if (r[5] or 0) // 100 == 5) / n * 100,
        'n1': sum(1 for r in rows if r[0] in n1_ids) / n * 100,
    }


def _activity(ranges, ep):
    from silk.models import Request
    lo = min(ranges[0][0], ranges[1][0])
    hi = max(ranges[0][1], ranges[1][1])
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    width = (hi - lo) / ACTIVITY_BUCKETS
    counts = [0] * ACTIVITY_BUCKETS
    times = Request.objects.filter(_range_q((lo, hi), ep)).values_list('start_time', flat=True)[:100000]
    for t in times:
        counts[min(ACTIVITY_BUCKETS - 1, int((t - lo) / width))] += 1
    top = max(counts) or 1
    bars = []
    for i, c in enumerate(counts):
        mid = lo + width * (i + .5)
        side = 'in-a' if ranges[0][0] <= mid < ranges[0][1] else 'in-b' if ranges[1][0] <= mid < ranges[1][1] else ''
        bars.append({'h': max(8, round(c / top * 100)) if c else 0, 'cls': side, 'n': c})
    return {'bars': bars, 'lo': lo, 'hi': hi}


def _endpoint_counts(rng):
    from silk.models import Request
    by = {}
    for g in Request.objects.filter(_range_q(rng, '')).order_by().values('view_name', 'path').annotate(n=Count('id')):
        key = endpoint_key(g['view_name'], g['path'])
        by[key] = by.get(key, 0) + g['n']
    return by


def compare_ranges(a, b, ep=''):
    from silk.models import SQLQuery
    ra, rb = _rows(a, ep), _rows(b, ep)
    n1 = repeating_request_ids()
    db_a = SQLQuery.objects.filter(_range_q(a, ep, 'request__')).aggregate(ms=Sum('time_taken'))['ms'] or 0
    db_b = SQLQuery.objects.filter(_range_q(b, ep, 'request__')).aggregate(ms=Sum('time_taken'))['ms'] or 0
    A, B = _agg(ra, n1, db_a), _agg(rb, n1, db_b)

    if not ra or not rb:
        verdict = {'kind': 'neutral', 'headline': 'Not enough data:',
                   'detail': f'{"B" if ra else "A"} has no requests{" for this endpoint" if ep else ""}. Widen the range or pick a preset.'}
    else:
        d95 = (B['p95'] - A['p95']) / A['p95'] * 100 if A['p95'] else 0
        dq = B['q'] - A['q']
        same = abs(d95) < 5
        queries = ('queries per request unchanged' if abs(dq) < .5
                   else f'queries per request {"down" if dq < 0 else "up"} from {A["q"]:.1f} to {B["q"]:.1f}')
        verdict = {'kind': 'neutral' if same else 'ok' if d95 < 0 else 'bad',
                   'headline': 'p95 about the same' if same else f'p95 {abs(d95):.0f}% {"lower" if d95 < 0 else "higher"} in B',
                   'detail': f'({fmt_ms(A["p95"])} → {fmt_ms(B["p95"])}), {queries}. Based on {len(ra)} and {len(rb)} requests.'}

    def row(label, key, fmt, lower=True):
        return {'label': label, 'a': A[key], 'b': B[key], 'fmt': fmt,
                'change': _change(A[key], B[key], lower, fmt) if lower is not None else
                {'text': f'{"+" if B[key] - A[key] > 0 else ""}{B[key] - A[key]:.0f}', 'cls': ''}}

    metrics = [row('Requests', 'n', 'int', None), row('p50', 'p50', 'ms'), row('p95', 'p95', 'ms'),
               row('Queries per request', 'q', 'f1'), row('DB time per request', 'db', 'ms'),
               row('5xx rate', 'err', 'pct'), row('Requests with N+1', 'n1', 'pct')]

    endpoints = []
    if not ep:
        def group(rows):
            by = {}
            for r in rows:
                by.setdefault(endpoint_key(r[3], r[4]), []).append(r)
            return by
        ga, gb = group(ra), group(rb)
        for key in set(ga) | set(gb):
            ea, eb = ga.get(key, []), gb.get(key, [])
            sa, sb = _agg(ea, n1, 0), _agg(eb, n1, 0)
            endpoints.append({'key': key, 'a': sa, 'b': sb,
                              'd': sb['p95'] - sa['p95'] if ea and eb else None,
                              'kind': 'new' if not ea else 'gone' if not eb else '',
                              'change': _change(sa['p95'], sb['p95']) if ea and eb else None})
        endpoints.sort(key=lambda e: -(e['d'] if e['d'] is not None else float('-inf')))

    pa = _pattern_rows(SQLQuery.objects.filter(_range_q(a, ep, 'request__')))
    pb = _pattern_rows(SQLQuery.objects.filter(_range_q(b, ep, 'request__')))
    na, nb = len(ra) or 1, len(rb) or 1
    patterns = []
    for h in set(pa) | set(pb):
        x, y = pa.get(h) or {}, pb.get(h) or {}
        ca, cb = x.get('n', 0) / na, y.get('n', 0) / nb
        if abs(cb - ca) < .1:
            continue
        ma, mb = (x.get('ms') or 0) / na, (y.get('ms') or 0) / nb
        patterns.append({'pattern_hash': h, 'a': ca, 'b': cb, 'sample': (x or y)['sample'],
                         'dms': mb - ma, 'change': _change(ma, mb)})
    patterns.sort(key=lambda p: -abs(p['dms']))
    patterns = _with_sql(patterns[:PATTERNS_SHOWN])

    counts_a, counts_b = _endpoint_counts(a), _endpoint_counts(b)
    menu = sorted(set(counts_a) | set(counts_b), key=lambda k: -(counts_a.get(k, 0) + counts_b.get(k, 0)))[:ENDPOINTS_IN_MENU]
    return {
        'A': A, 'B': B, 'verdict': verdict, 'metrics': metrics, 'endpoints': endpoints, 'patterns': patterns,
        'low_sample': (0 < len(ra) < 10) or (0 < len(rb) < 10),
        'activity': _activity((a, b), ep),
        'menu': [{'key': k, 'na': counts_a.get(k, 0), 'nb': counts_b.get(k, 0)} for k in menu],
    }
