"""Data for the Profiling page: silk_profile runs grouped into code blocks, and cProfile output.

A code block is every run sharing a name, function, file and line. Run stats
and SQL stats are read in two grouped queries, because joining the queries
table would multiply each run's time by its query count.
"""
import re

from django.db.models import Count, Max, Q, Sum

from silk.utils.sql_patterns import histogram

BLOCK_FIELDS = ('name', 'func_name', 'file_path', 'line_num')
BLOCK_SORTS = {'total': 'total', 'avg': 'avg', 'count': 'runs', 'max': 'max'}
RUNS_SHOWN = 40
CPROFILE_MAX = 200

_CPROFILE_HEAD = re.compile(r'([\d,]+) function calls.*? in ([\d.]+) seconds')
_CPROFILE_ROW = re.compile(r'^\s*([\d/]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+)$')
_CPROFILE_FN = re.compile(r'^(.*):(\d+)\((.*)\)$')


def _key(row):
    return tuple(row[f] for f in BLOCK_FIELDS)


def blocks(qs, sort='total'):
    """One row per code block, sorted by `sort` (total, avg, count or max)."""
    runs = list(qs.order_by().values(*BLOCK_FIELDS).annotate(
        runs=Count('id'), total=Sum('time_taken'), max=Max('time_taken'),
        newest=Max('id'), raised=Count('id', filter=Q(exception_raised=True))))
    sql = {_key(r): r for r in qs.order_by().values(*BLOCK_FIELDS).annotate(
        sql_n=Count('queries'), sql_ms=Sum('queries__time_taken'))}
    top = max((r['total'] or 0 for r in runs), default=0) or 1
    rows = []
    for r in runs:
        s = sql.get(_key(r), {})
        total = r['total'] or 0
        rows.append({
            **r, 'id': r['newest'], 'total': total, 'max': r['max'] or 0, 'avg': total / r['runs'],
            'raised': r['raised'] or 0,
            'avg_q': (s.get('sql_n') or 0) / r['runs'],
            'sql_share': min(100, (s.get('sql_ms') or 0) / total * 100) if total else 0,
            'bar': max(2, total / top * 100),
        })
    key = BLOCK_SORTS.get(sort, 'total')
    rows.sort(key=lambda b: -b[key])
    return rows


def block_detail(qs, profile_id):
    """The block that profile `profile_id` belongs to, with its slowest runs."""
    sample = qs.filter(pk=profile_id).values(*BLOCK_FIELDS).first()
    if not sample:
        return None
    runs_qs = qs.filter(**sample)
    stats = blocks(runs_qs)[0]
    runs = list(runs_qs.select_related('request').annotate(nq=Count('queries')).order_by('-time_taken')[:RUNS_SHOWN])
    return {
        **sample, 'stats': stats,
        'hist': histogram(list(runs_qs.values_list('time_taken', flat=True)), bins=20),
        'runs': runs,
    }


def cprofile_requests(qs):
    """Requests that carry cProfile output, slowest first. The output itself is not loaded."""
    return list(qs.exclude(pyprofile='').select_related('response')
                .only('id', 'method', 'path', 'view_name', 'time_taken', 'start_time', 'num_sql_queries',
                      'response__status_code')
                .order_by('-time_taken')[:CPROFILE_MAX])


def parse_cprofile(text, sort='cumtime'):
    """Function rows from pstats text output, with bars scaled to the largest value of `sort`."""
    head = _CPROFILE_HEAD.search(text or '')
    rows = []
    for line in (text or '').splitlines():
        m = _CPROFILE_ROW.match(line)
        if not m:
            continue
        fn = _CPROFILE_FN.match(m.group(6))
        rows.append({
            'ncalls': m.group(1), 'tottime': float(m.group(2)) * 1000, 'cumtime': float(m.group(4)) * 1000,
            'name': fn.group(3) if fn else m.group(6), 'file': fn.group(1) if fn else '',
            'line': fn.group(2) if fn else '',
        })
    if sort not in ('cumtime', 'tottime'):
        sort = 'cumtime'
    rows.sort(key=lambda r: -r[sort])
    top = rows[0][sort] if rows and rows[0][sort] else 1
    for r in rows:
        r['bar'] = r[sort] / top * 100
        r['value'] = r[sort]
    return {
        'calls': head.group(1) if head else '',
        'ms': float(head.group(2)) * 1000 if head else 0,
        'rows': rows, 'sort': sort,
    }
