"""Developer-facing insights for one recorded request.

Turns raw Silk data into answers: which line of the app ran a query, whether
a repeated query is an N+1 or a plain duplicate, the likely fix, what is usual
for the endpoint, and a test that pins the query count.
"""
import os
import re
import statistics
import sys
import sysconfig

from silk.utils.n_plus_one import detect_n_plus_one
from silk.utils.prefs import N1_MIN

_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
_SILK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A request this far above the endpoint's median is flagged as unusual.
SLOWER_FACTOR = 3
SLOWER_MIN_MS = 200
MIN_REQUESTS_FOR_USUAL = 5


def _stdlib_dirs():
    """Where the standard library lives, also resolved, since Homebrew and pyenv reach it through symlinks."""
    paths = sysconfig.get_paths()
    dirs = {os.path.dirname(os.__file__), paths.get('stdlib'), paths.get('platstdlib')}
    dirs |= {os.path.realpath(d) for d in dirs if d}
    return tuple(d.rstrip(os.sep) + os.sep for d in dirs if d)


_STDLIB_DIRS = _stdlib_dirs()


def _is_app_file(path):
    if 'site-packages' in path or path.startswith(_SILK_DIR) or path.startswith(_STDLIB_DIRS):
        return False
    lib_path = os.environ.get('VIRTUAL_ENV') or sys.prefix
    return not (lib_path and path.startswith(lib_path))


def _is_db_frame(path):
    return path.startswith(_SILK_DIR) or '/django/db/' in path.replace('\\', '/')


def parse_frames(traceback):
    """Frames of a recorded traceback in stored order: file, line, func, code and whether it is app code."""
    lines = (traceback or '').split('\n')
    frames = []
    for i, raw in enumerate(lines):
        m = _FRAME.search(raw)
        if not m:
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
        frames.append({
            'file': m.group('file'),
            'line': int(m.group('line')),
            'func': m.group('func'),
            'code': '' if _FRAME.search(nxt) else nxt,
            'app': _is_app_file(m.group('file')),
        })
    return frames


def lib_path(path):
    """A library path from its package directory on ('rest_framework/views.py'), or the last two parts."""
    norm = path.replace('\\', '/')
    for marker in ('site-packages/', 'dist-packages/'):
        if marker in norm:
            return norm.split(marker, 1)[1]
    return '/'.join(norm.split('/')[-2:])


def app_frame(traceback):
    """The app's own frame closest to the database call in a recorded traceback, or None.

    Silk's middleware stores stacks innermost first (silk/sql.py reverses them);
    a standard Python traceback is outermost first. The side the database and
    Silk frames sit on tells the order. Returns a dict with file, line, func and
    code (the source line, if recorded), plus 'via': the library frame nearest
    the database between that line and the query, or None. When the query comes
    from a library the app line only hands control to (a middleware calling
    get_response, a view returning serializer.data), 'via' is the code that ran it.
    """
    frames = parse_frames(traceback)
    if not any(f['app'] for f in frames):
        return None
    if not (_is_db_frame(frames[0]['file']) and not _is_db_frame(frames[-1]['file'])):
        frames.reverse()
    i = next(i for i, f in enumerate(frames) if f['app'])
    via = next((f for f in frames[:i] if not _is_db_frame(f['file'])), None)
    return {**frames[i], 'via': {**via, 'short': lib_path(via['file'])} if via else None}


LOCATION_MAX = 300


def code_location(traceback):
    """'path:line' of the app frame that ran a query, sized for SQLQuery.code_location, or ''."""
    frame = app_frame(traceback)
    if not frame:
        return ''
    suffix = ':%d' % frame['line']
    return frame['file'][-(LOCATION_MAX - len(suffix)):] + suffix


def repeat_kind(queries):
    """'dup' when every query in the group is byte-identical, otherwise 'n1'.

    Silk stores SQL with parameters interpolated, so identical text means the
    same parameters: the same rows fetched again. Different text with the same
    shape is one lookup per row: an N+1.
    """
    return 'dup' if len({q.query for q in queries}) == 1 else 'n1'


# Django names tables <app_label>_<model>. App labels may contain underscores but
# model names never do, so the model is everything after the last underscore.
_FK_LOOKUP = re.compile(r'FROM "(\w+)".*WHERE "\1"\."id" = ', re.S | re.I)
_REVERSE_FK = re.compile(r'FROM "(\w+)".*WHERE "\1"\."(\w+)_id" = ', re.S | re.I)


def _model_name(table):
    return table.rsplit('_', 1)[-1]


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
        model = _model_name(fk.group(1))
        cls = model.capitalize()
        return {
            'kind': kind,
            'text': f'Each row loads a {model} by its id, one query per row. If the rows reach it through a '
                    f'relation, join it in the original query; if you have the ids, load them all at once.',
            'code': f"queryset = queryset.select_related('{model}')  # rows reach {model} through a relation\n"
                    f"{cls}.objects.in_bulk(ids)  # or: you already have the ids",
        }
    rev = _REVERSE_FK.search(sql)
    if rev:
        model = _model_name(rev.group(1))
        return {
            'kind': kind,
            'text': f'Each {rev.group(2)} loads its {model} rows separately. Load them all in one extra query.',
            'code': f"queryset = queryset.prefetch_related('{model}_set')  # or the related_name you set",
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


def request_insights(silk_request, queries, repeat_min=N1_MIN):
    """Everything the request overview shows, from the request and its queries."""
    result = detect_n_plus_one(queries, repeat_min)
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
