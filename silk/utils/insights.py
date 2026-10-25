"""Developer-facing insights for one recorded request.

Turns raw Silk data into answers: which line of the app ran a query, whether
a repeated query is an N+1 or a plain duplicate, the likely fix, what is usual
for the endpoint, and a test that pins the query count.
"""
import os
import re
import statistics
import sys

from silk.utils.n_plus_one import detect_n_plus_one

_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
_SILK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A request this far above the endpoint's median is flagged as unusual.
SLOWER_FACTOR = 3
SLOWER_MIN_MS = 200
MIN_REQUESTS_FOR_USUAL = 5


def _is_app_file(path):
    if 'site-packages' in path or path.startswith(_SILK_DIR):
        return False
    lib_path = os.environ.get('VIRTUAL_ENV') or sys.prefix
    return not (lib_path and path.startswith(lib_path))


def app_frame(traceback):
    """The innermost frame of the app's own code in a recorded traceback, or None.

    Returns a dict with file, line, func and code (the source line, if recorded).
    """
    lines = (traceback or '').split('\n')
    found = None
    for i, raw in enumerate(lines):
        m = _FRAME.search(raw)
        if not m or not _is_app_file(m.group('file')):
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
        found = {
            'file': m.group('file'),
            'line': int(m.group('line')),
            'func': m.group('func'),
            'code': '' if _FRAME.search(nxt) else nxt,
        }
    return found


def repeat_kind(queries):
    """'dup' when every query in the group is byte-identical, otherwise 'n1'.

    Silk stores SQL with parameters interpolated, so identical text means the
    same parameters: the same rows fetched again. Different text with the same
    shape is one lookup per row: an N+1.
    """
    return 'dup' if len({q.query for q in queries}) == 1 else 'n1'


_FK_LOOKUP = re.compile(r'FROM "(\w+?)_(\w+)".*WHERE "\1_\2"\."id" = ', re.S | re.I)
_REVERSE_FK = re.compile(r'FROM "(\w+?)_(\w+)".*WHERE "\1_\2"\."(\w+)_id" = ', re.S | re.I)


def suggest_fix(queries):
    """A likely fix for a repeated query, as {'kind', 'text', 'code'}.

    Read from the SQL, so it is a starting point rather than a guarantee.
    """
    kind = repeat_kind(queries)
    count = len(queries)
    if kind == 'dup':
        return {
            'kind': kind,
            'text': f'The same query with the same parameters ran {count} times. Run it once and reuse the result, or cache it.',
            'code': '# fetch once, outside the loop\nresult = list(qs)\n'
                    '# or, for values reused across requests\nfrom django.core.cache import cache\n'
                    'result = cache.get_or_set("key", lambda: list(qs), 60)',
        }
    sql = queries[0].query
    fk = _FK_LOOKUP.search(sql)
    if fk:
        return {
            'kind': kind,
            'text': f'Each row looks up its related {fk.group(2)} separately. Fetch it in the original query with a join.',
            'code': f"queryset = queryset.select_related('{fk.group(2)}')",
        }
    rev = _REVERSE_FK.search(sql)
    if rev:
        return {
            'kind': kind,
            'text': f'Each {rev.group(3)} loads its {rev.group(2)} rows separately. Load them all in one extra query.',
            'code': f"queryset = queryset.prefetch_related('{rev.group(2)}_set')  # or the related_name you set",
        }
    return {
        'kind': kind,
        'text': f'The same query shape ran {count} times with different values, typically once per row in a loop. Fetch the related rows up front.',
        'code': 'queryset = queryset.select_related(...)  # forward FK / one-to-one\n'
                'queryset = queryset.prefetch_related(...)  # reverse FK / many-to-many',
    }


def usual_for(silk_request):
    """Median time and query count for the request's endpoint, and how this request compares.

    Returns None when the endpoint has fewer than MIN_REQUESTS_FOR_USUAL recordings.
    """
    from silk.models import Request
    key = {'view_name': silk_request.view_name} if silk_request.view_name else {'path': silk_request.path}
    rows = list(Request.objects.filter(**key).values_list('time_taken', 'num_sql_queries'))
    if len(rows) < MIN_REQUESTS_FOR_USUAL:
        return None
    ms = statistics.median([t or 0 for t, _ in rows])
    nq = statistics.median([n or 0 for _, n in rows])
    taken = silk_request.time_taken or 0
    slower = taken / ms if ms else 0
    extra = silk_request.num_sql_queries - nq
    return {
        'endpoint': silk_request.view_name or silk_request.path,
        'ms': ms,
        'queries': nq,
        'n': len(rows),
        'slower_x': slower if slower >= SLOWER_FACTOR and taken - ms >= SLOWER_MIN_MS else 0,
        'extra_queries': extra if extra >= max(10, nq) else 0,
    }


def query_count_test(silk_request, repeated_groups):
    """Django test code that fails if the request's query count goes up."""
    method = silk_request.method.lower()
    class_name = re.sub(r'[^0-9a-zA-Z]+', ' ', silk_request.view_name or 'view').title().replace(' ', '')
    saved = sum(g['count'] - 1 for g in repeated_groups)
    total = silk_request.num_sql_queries
    if saved:
        note = (f'        # Recorded {total} queries; {saved} are repeats. After fixing them, expect about {total - saved}\n'
                '        # and lower the number below so the fix is locked in.\n')
    else:
        note = f'        # Recorded {total} queries. Fails if a change adds queries to this view.\n'
    return (
        'from django.test import TestCase\n\n\n'
        f'class {class_name}Test(TestCase):\n'
        f'    def test_{method}_query_count(self):\n'
        f'{note}'
        f'        with self.assertNumQueries({total}):\n'
        f"            response = self.client.{method}('{silk_request.path}')\n"
        f'        self.assertEqual(response.status_code, {getattr(getattr(silk_request, "response", None), "status_code", 200) or 200})\n'
    )


def request_insights(silk_request, queries):
    """Everything the request overview shows, from the request and its queries."""
    result = detect_n_plus_one(queries)
    groups = []
    for g in result.groups:
        frame = app_frame(g.representative.traceback)
        groups.append({
            'count': g.count,
            'total_ms': g.total_time_taken,
            'kind': repeat_kind(g.queries),
            'fix': suggest_fix(g.queries),
            'frame': frame,
            'sql': g.representative.query,
        })
    db_ms = sum(q.time_taken or 0 for q in queries)
    total_ms = silk_request.time_taken or 0
    slowest = sorted(queries, key=lambda q: q.time_taken or 0, reverse=True)[:5]
    top_ms = (slowest[0].time_taken or 0) if slowest else 0
    return {
        'db_ms': db_ms,
        'sql_pct': min(100, db_ms / total_ms * 100) if total_ms else 0,
        'repeated': groups,
        'n1_count': sum(1 for g in groups if g['kind'] == 'n1'),
        'dup_count': sum(1 for g in groups if g['kind'] == 'dup'),
        'repeat_queries': sum(g['count'] for g in groups),
        'slowest': [{'query': q, 'pct': (q.time_taken or 0) / top_ms * 100 if top_ms else 0, 'frame': app_frame(q.traceback)} for q in slowest],
        'usual': usual_for(silk_request),
        'test_code': query_count_test(silk_request, groups),
    }
