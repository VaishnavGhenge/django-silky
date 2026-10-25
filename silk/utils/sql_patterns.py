"""Aggregate recorded SQL by query shape (pattern) and by calling line (hotspot).

Grouping uses SQLQuery.pattern_hash and SQLQuery.code_location, which are
filled when a query is saved, so everything here is a GROUP BY in the database.
No aggregate touches the SQL text column itself: it is a LOB on Oracle, which
cannot be grouped or compared.
"""
import re
from collections import Counter

import sqlparse
from django.db import connection
from django.db.models import Avg, Count, Max, Min, Sum

from silk.utils.insights import app_frame, repeat_kind, suggest_fix

# A pattern that runs this many times inside one request is flagged as repeating.
REPEAT_MIN = 3
_TABLE = re.compile(r'\b(?:FROM|INTO|UPDATE)\s+[`"\[]?([\w.]+)', re.I)
_TYPE = re.compile(r'^\s*(SELECT|INSERT|UPDATE|DELETE)\b', re.I)


def sql_type(sql):
    m = _TYPE.match(sql or '')
    return m.group(1).upper() if m else 'OTHER'


def sql_table(sql):
    m = _TABLE.search(sql or '')
    return m.group(1) if m else '?'


def _queries():
    from silk.models import SQLQuery
    return SQLQuery.objects.order_by()


def repeating_patterns():
    """{pattern_hash: number of requests in which it ran REPEAT_MIN or more times}."""
    from silk.models import SQLQuery
    table = connection.ops.quote_name(SQLQuery._meta.db_table)
    # Two-level GROUP BY so the database returns one row per pattern; the
    # (pattern_hash, request_id) index makes the inner grouping cheap.
    sql = (
        f'SELECT t.pattern_hash, COUNT(*) FROM ('
        f'SELECT pattern_hash, request_id, COUNT(*) AS c FROM {table} '
        f'GROUP BY pattern_hash, request_id) t WHERE t.c >= %s GROUP BY t.pattern_hash'
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [REPEAT_MIN])
        return dict(cursor.fetchall())


def looping_locations():
    """{code_location: number of requests in which that line ran REPEAT_MIN or more queries}.

    A line that runs several queries in one request sits in a loop: the usual N+1 shape.
    """
    from silk.models import SQLQuery
    table = connection.ops.quote_name(SQLQuery._meta.db_table)
    sql = (
        f'SELECT t.code_location, COUNT(*) FROM ('
        f"SELECT code_location, request_id, COUNT(*) AS c FROM {table} WHERE code_location <> '' "
        f'GROUP BY code_location, request_id) t WHERE t.c >= %s GROUP BY t.code_location'
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [REPEAT_MIN])
        return dict(cursor.fetchall())


def _samples(ids):
    rows = _queries().filter(pk__in=ids).values('pk', 'query', 'traceback')
    return {r['pk']: r for r in rows}


def patterns():
    """One dict per query pattern: calls, timings, requests, table, type, repeat count."""
    rows = list(
        _queries().values('pattern_hash').annotate(
            calls=Count('id'), total=Sum('time_taken'), avg=Avg('time_taken'), max=Max('time_taken'),
            requests=Count('request', distinct=True), sample=Min('id'),
        ).order_by('-total')
    )
    samples = _samples([r['sample'] for r in rows])
    repeats = repeating_patterns()
    for r in rows:
        sql = samples.get(r['sample'], {}).get('query', '')
        r.update(sql=sql, table=sql_table(sql), type=sql_type(sql), repeats=repeats.get(r['pattern_hash'], 0),
                 total=r['total'] or 0, avg=r['avg'] or 0, max=r['max'] or 0)
    return rows


def tables(pattern_rows):
    """DB time per table, largest first."""
    by = Counter()
    calls = Counter()
    for p in pattern_rows:
        by[p['table']] += p['total']
        calls[p['table']] += p['calls']
    return [{'table': t, 'total': ms, 'calls': calls[t]} for t, ms in by.most_common()]


def histogram(values, bins=24):
    values = [v for v in values if v is not None]
    if not values:
        return {'bars': [], 'max': 0}
    top = max(values) or 1
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int(v / top * bins))] += 1
    peak = max(counts) or 1
    return {'bars': [max(4, round(c / peak * 100)) if c else 0 for c in counts], 'max': top}


def pattern_detail(pattern_hash):
    """Everything the pattern panel shows, or None if the pattern no longer exists."""
    from silk.models import Request
    qs = _queries().filter(pattern_hash=pattern_hash)
    stats = qs.aggregate(calls=Count('id'), total=Sum('time_taken'), avg=Avg('time_taken'),
                         max=Max('time_taken'), requests=Count('request', distinct=True), sample=Min('id'))
    if not stats['calls']:
        return None
    sample = _samples([stats['sample']])[stats['sample']]
    per_request = list(qs.values('request_id').annotate(n=Count('id')).order_by('-n', '-request_id')[:40])
    reqs = Request.objects.select_related('response').in_bulk([r['request_id'] for r in per_request if r['request_id']])
    occurrences = [{'request': reqs[r['request_id']], 'n': r['n']} for r in per_request if r['request_id'] in reqs]

    top_loc = qs.exclude(code_location='').values('code_location').annotate(n=Count('id')).order_by('-n').first()
    frame = None
    if top_loc:
        tb = qs.filter(code_location=top_loc['code_location']).values_list('traceback', flat=True).first()
        frame = app_frame(tb)

    fix = None
    if occurrences and occurrences[0]['n'] >= REPEAT_MIN:
        group = list(qs.filter(request_id=occurrences[0]['request'].pk)[:50])
        fix = suggest_fix(group)
        fix['kind'] = repeat_kind(group)

    return {
        'pattern_hash': pattern_hash,
        'stats': {k: (v or 0) for k, v in stats.items()},
        'sql': sample['query'],
        'formatted': sqlparse.format(sample['query'], reindent=True, keyword_case='upper'),
        'table': sql_table(sample['query']),
        'type': sql_type(sample['query']),
        'frame': frame,
        'fix': fix,
        'hist': histogram(list(qs.values_list('time_taken', flat=True)[:5000])),
        'occurrences': occurrences,
        'repeat_min': REPEAT_MIN,
    }


def hotspots():
    """One dict per calling line: queries, requests, DB time, and whether it runs repeating patterns."""
    rows = list(
        _queries().exclude(code_location='').values('code_location').annotate(
            calls=Count('id'), total=Sum('time_taken'), requests=Count('request', distinct=True), sample=Min('id'),
        ).order_by('-total')
    )
    samples = _samples([r['sample'] for r in rows])
    looping = looping_locations()
    total_all = sum(r['total'] or 0 for r in rows) or 1
    for r in rows:
        frame = app_frame(samples.get(r['sample'], {}).get('traceback', '')) or {}
        r.update(
            total=r['total'] or 0,
            share=(r['total'] or 0) / total_all * 100,
            per_request=r['calls'] / r['requests'] if r['requests'] else r['calls'],
            file=frame.get('file', r['code_location'].rsplit(':', 1)[0]),
            line=frame.get('line', 0),
            func=frame.get('func', ''),
            code=frame.get('code', ''),
            repeats=looping.get(r['code_location'], 0),
        )
    return rows


def hotspot_detail(location):
    """Queries a calling line runs, the endpoints that reach it, and a likely fix."""
    qs = _queries().filter(code_location=location)
    stats = qs.aggregate(calls=Count('id'), total=Sum('time_taken'), requests=Count('request', distinct=True), sample=Min('id'))
    if not stats['calls']:
        return None
    frame = app_frame(_samples([stats['sample']])[stats['sample']]['traceback']) or {}
    pats = list(qs.values('pattern_hash').annotate(calls=Count('id'), total=Sum('time_taken'), sample=Min('id')).order_by('-total'))
    samples = _samples([p['sample'] for p in pats])
    repeats = repeating_patterns()
    for p in pats:
        sql = samples.get(p['sample'], {}).get('query', '')
        p.update(sql=sql, table=sql_table(sql), type=sql_type(sql), repeats=repeats.get(p['pattern_hash'], 0), total=p['total'] or 0)
    endpoints = list(qs.values('request__view_name', 'request__path').annotate(n=Count('id')).order_by('-n')[:20])

    fix = None
    worst = next((p for p in pats if p['repeats']), None)
    if worst:
        top = (qs.filter(pattern_hash=worst['pattern_hash']).values('request_id')
               .annotate(n=Count('id')).order_by('-n').first())
        group = list(qs.filter(pattern_hash=worst['pattern_hash'], request_id=top['request_id'])[:50])
        fix = suggest_fix(group)
        fix['kind'] = repeat_kind(group)

    calls = stats['calls']
    return {
        'location': location,
        'stats': {k: (v or 0) for k, v in stats.items()},
        'per_request': calls / stats['requests'] if stats['requests'] else calls,
        'file': frame.get('file', location.rsplit(':', 1)[0]),
        'line': frame.get('line', 0),
        'func': frame.get('func', ''),
        'code': frame.get('code', ''),
        'patterns': pats,
        'endpoints': endpoints,
        'fix': fix,
    }
