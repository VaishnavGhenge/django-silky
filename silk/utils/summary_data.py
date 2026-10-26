"""Data for the Summary page, computed from one pass over the filtered requests.

The requests are read once as compact tuples (at most MAX_ROWS, newest first);
headline numbers, the latency chart, endpoint health, the scatter and the
heatmap are all derived from that list in Python.
"""
import math
import statistics

from django.core.cache import cache
from django.db import connection

from silk.utils.fmt import fmt_ms
from silk.utils.prefs import N1_MIN

MAX_ROWS = 20000      # requests read for the page
SCATTER_MAX = 400     # dots drawn in the scatter (newest); each is a link, so this bounds the HTML
LINE_BUCKETS = 24
HEAT_COLS, HEAT_ROWS = 36, 10
REPEAT_MIN = N1_MIN   # default; each viewer can change it in Settings


def _pct(sorted_vals, p):
    if not sorted_vals:
        return 0
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))]


N1_CACHE_SECONDS = 30
N1_CACHE_MAX = 10000  # ids kept in the cache; larger sets are recomputed (memcached caps values at 1 MB)


def repeating_request_ids(repeat_min=REPEAT_MIN):
    """Ids (as strings) of requests where some query pattern ran repeat_min or more times (likely N+1).

    The GROUP BY reads every recorded query, and the sidebar, Requests stats and
    Summary all ask for it, so the result is cached briefly. The key carries the
    newest query id, so newly recorded requests show up at once.
    """
    from silk.models import SQLQuery
    newest = SQLQuery.objects.order_by('-id').values_list('id', flat=True).first()
    key = f'silky:n1ids:{repeat_min}:{newest}'
    ids = cache.get(key)
    if ids is not None:
        return ids
    table = connection.ops.quote_name(SQLQuery._meta.db_table)
    sql = (f'SELECT DISTINCT request_id FROM {table} WHERE request_id IS NOT NULL '
           f'GROUP BY pattern_hash, request_id HAVING COUNT(*) >= %s')
    with connection.cursor() as cursor:
        cursor.execute(sql, [repeat_min])
        ids = {str(r[0]) for r in cursor.fetchall()}
    if len(ids) <= N1_CACHE_MAX:
        cache.set(key, ids, N1_CACHE_SECONDS)
    return ids


def load_rows(filters, repeat_min=REPEAT_MIN):
    from silk.models import Request
    qs = Request.objects.filter(*filters).filter(time_taken__isnull=False).order_by('-start_time')
    rows = list(qs.values_list('id', 'time_taken', 'num_sql_queries', 'view_name', 'path', 'method',
                               'start_time', 'response__status_code')[:MAX_ROWS])
    n1 = repeating_request_ids(repeat_min)
    return [
        {'id': r[0], 'ms': r[1] or 0, 'q': r[2] or 0, 'ep': r[3] or r[4], 'path': r[4], 'method': r[5],
         't': r[6], 'sc': (r[7] or 0) // 100, 'n1': str(r[0]) in n1}
        for r in rows
    ]


def headline(rows):
    ms = sorted(r['ms'] for r in rows)
    n = len(rows) or 1
    errors = sum(1 for r in rows if r['sc'] == 5)
    return {
        'count': len(rows),
        'p50': _pct(ms, .5),
        'p95': _pct(ms, .95),
        'errors': errors,
        'error_rate': errors / n * 100,
        'avg_queries': sum(r['q'] for r in rows) / n,
        'n1': sum(1 for r in rows if r['n1']),
    }


def latency_chart(rows):
    """p50 and p95 per bucket of requests in time order, as SVG paths on a 600x200 box."""
    ordered = sorted(rows, key=lambda r: r['t'])
    if len(ordered) < 4:
        return None
    size = math.ceil(len(ordered) / LINE_BUCKETS)
    p50, p95 = [], []
    for i in range(0, len(ordered), size):
        chunk = sorted(r['ms'] for r in ordered[i:i + size])
        p50.append(_pct(chunk, .5))
        p95.append(_pct(chunk, .95))
    top = max(p95) or 1
    w, h = 600, 200

    def y(v):
        return h - 4 - v / top * (h - 12)

    def path(vals):
        step = w / max(1, len(vals) - 1)
        return ' '.join(f"{'L' if i else 'M'}{i * step:.1f} {y(v):.1f}" for i, v in enumerate(vals))
    ticks = [{'label': v, 'pct': y(v) / h * 100} for v in (top, top * .75, top * .5, top * .25, 0)]
    return {'p50': path(p50), 'p95': path(p95), 'area': path(p95) + f' L{w} {h} L0 {h} Z',
            'ticks': ticks, 'grid': [round(y(top * f), 1) for f in (1, .75, .5, .25, 0)],
            'requests': len(ordered), 'buckets': len(p50)}


def endpoints(rows):
    """Health per endpoint, plus the three that cost the most total time."""
    by = {}
    for r in rows:
        by.setdefault(r['ep'], []).append(r)
    total = sum(r['ms'] for r in rows) or 1
    eps = []
    for key, rs in by.items():
        ms = sorted(r['ms'] for r in rs)
        n = len(rs)
        trend = [r['ms'] for r in sorted(rs, key=lambda r: r['t'])[-20:]]
        top = max(trend) or 1
        spark = ' '.join(f"{'L' if i else 'M'}{i / max(1, len(trend) - 1) * 60:.1f} {17 - v / top * 15:.1f}" for i, v in enumerate(trend)) if len(trend) > 1 else ''
        eps.append({
            'key': key, 'count': n, 'p50': _pct(ms, .5), 'p95': _pct(ms, .95),
            'avg_q': sum(r['q'] for r in rs) / n,
            'err': sum(1 for r in rs if r['sc'] == 5) / n * 100,
            'n1': sum(1 for r in rs if r['n1']),
            'impact': sum(ms), 'share': sum(ms) / total * 100, 'spark': spark,
        })
    eps.sort(key=lambda e: -e['impact'])
    return eps


def focus(eps, slow_ms=1000):
    """'Fix these first': top endpoints by total time, with the reasons that make them costly."""
    out = []
    for e in eps[:3]:
        reasons = []
        if e['p95'] >= slow_ms:
            reasons.append(('bad', f"p95 {fmt_ms(e['p95'])}"))
        if e['n1']:
            reasons.append(('warn', f"N+1 in {e['n1']}/{e['count']}"))
        if e['avg_q'] >= 20:
            reasons.append(('warn', f"{e['avg_q']:.0f} queries avg"))
        if e['err'] >= 5:
            reasons.append(('bad', f"{e['err']:.0f}% 5xx"))
        out.append({**e, 'reasons': reasons})
    return out


def status_breakdown(rows):
    counts = {d: sum(1 for r in rows if r['sc'] == d) for d in (2, 3, 4, 5)}
    return [{'digit': d, 'count': c} for d, c in counts.items()]


def _log_pos(ms, top):
    return math.log10(max(ms, 1)) / math.log10(max(top, 10))


def _log_ticks(top):
    ticks, v = [], 1
    while v <= top * 1.01:
        ticks.append({'label': v, 'pct': _log_pos(v, top) * 100})
        v *= 10
    return ticks


def _spearman(xs, ys):
    def rank(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            for k in range(i, j + 1):
                ranks[order[k]] = (i + j) / 2
            i = j + 1
        return ranks
    if len(xs) < 3:
        return 0
    rx, ry = rank(xs), rank(ys)
    try:
        return statistics.correlation(rx, ry)
    except statistics.StatisticsError:
        return 0


def scatter(rows):
    """Queries (x) against response time (y, log scale) for the newest SCATTER_MAX requests."""
    pts = rows[:SCATTER_MAX]
    if len(pts) < 3:
        return None
    max_q = max(r['q'] for r in pts) or 1
    top = max(r['ms'] for r in pts) or 1
    rho = _spearman([r['q'] for r in rows], [r['ms'] for r in rows])
    if rho >= .5:
        verdict = ('Time rises with query count', 'Cutting queries should help most.')
    elif rho >= .25:
        verdict = ('Some link to query count', 'Queries explain part of the slowness, not all of it.')
    else:
        verdict = ('Little link to query count', 'Slow requests here are slow for other reasons: Python work, outbound calls or a single slow query.')
    return {
        'dots': [{'id': r['id'], 'x': r['q'] / max_q * 100, 'y': _log_pos(r['ms'], top) * 100,
                  'cls': 'is-err' if r['sc'] == 5 else 'is-n1' if r['n1'] else '',
                  'title': f"{r['method']} {r['path']} · {fmt_ms(r['ms'])} · {r['q']} queries"} for r in pts],
        'yticks': _log_ticks(top), 'xticks': [round(max_q * f) for f in (0, .25, .5, .75, 1)],
        'rho': rho, 'verdict': verdict, 'shown': len(pts), 'total': len(rows),
    }


def heatmap(rows):
    """Request count per (time bucket, log latency band), oldest to newest."""
    ordered = sorted(rows, key=lambda r: r['t'])
    if len(ordered) < 6:
        return None
    top = max(r['ms'] for r in ordered) or 1
    cols = min(HEAT_COLS, len(ordered))
    size = len(ordered) / cols
    grid, peak = [], 1
    for c in range(cols):
        cells = [0] * HEAT_ROWS
        for r in ordered[int(c * size):int((c + 1) * size)]:
            cells[min(HEAT_ROWS - 1, int(_log_pos(r['ms'], top) * HEAT_ROWS))] += 1
        peak = max(peak, *cells)
        grid.append(cells)
    edge = [max(top, 10) ** (i / HEAT_ROWS) for i in range(HEAT_ROWS + 1)]
    columns = []
    for cells in grid:
        columns.append([{'n': n, 'alpha': round((.18 + .82 * n / peak) * 100) if n else 0,
                         'lo': edge[i], 'hi': edge[i + 1]} for i, n in reversed(list(enumerate(cells)))])
    return {'columns': columns, 'yticks': _log_ticks(top), 'first': ordered[0]['t'], 'last': ordered[-1]['t'], 'ncols': cols}
