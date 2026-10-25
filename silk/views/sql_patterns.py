from urllib.parse import urlencode

from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk.auth import login_possibly_required, permissions_possibly_required
from silk.utils import sql_patterns

SQL_SORTS = {
    'total': lambda p: -p['total'],
    'calls': lambda p: -p['calls'],
    'avg': lambda p: -p['avg'],
    'max': lambda p: -p['max'],
    'p95': lambda p: -p['p95'],
}
SQL_TYPES = ['SELECT', 'INSERT', 'UPDATE', 'DELETE']


def _template(request, page, partial):
    # htmx asks for the split view only; a normal visit gets the whole page.
    return partial if request.headers.get('HX-Request') else page


class SQLPatternsView(View):
    """Every recorded query, grouped by shape across all requests."""

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request):
        q = request.GET.get('q', '').strip().lower()
        typ = request.GET.get('type', '')
        table = request.GET.get('table', '')
        repeating = request.GET.get('repeating') == '1'
        slow = request.GET.get('slow') == '1'
        sort = request.GET.get('sort', 'total')
        if sort not in SQL_SORTS:
            sort = 'total'

        all_patterns = sql_patterns.patterns()
        p95 = sql_patterns.p95_by_pattern()
        for p in all_patterns:
            p['p95'] = p95.get(p['pattern_hash'], p['avg'])
        rows = [
            p for p in all_patterns
            if (not q or q in p['sql'].lower())
            and (not typ or p['type'] == typ)
            and (not table or p['table'] == table)
            and (not repeating or p['repeats'])
            and (not slow or p['p95'] >= sql_patterns.SLOW_PATTERN_MS)
        ]
        rows.sort(key=SQL_SORTS[sort])
        total_ms = sum(p['total'] for p in all_patterns)
        top = max([p['total'] for p in rows] + [1])
        for p in rows:
            p['bar'] = max(2, round(p['total'] / top * 100))
        table_rows = sql_patterns.tables(all_patterns)
        table_top = table_rows[0]['total'] if table_rows else 1
        for t in table_rows:
            t['bar'] = round(t['total'] / table_top * 100) if table_top else 0
            t['share'] = t['total'] / total_ms * 100 if total_ms else 0

        # Current filters as a query string, so row and close links keep them.
        qs = urlencode([(k, v) for k, v in [('q', q), ('type', typ), ('table', table),
                                             ('repeating', '1' if repeating else ''), ('slow', '1' if slow else ''),
                                             ('sort', '' if sort == 'total' else sort)] if v])
        open_hash = request.GET.get('p', '')
        context = {
            'rows': rows[:200],
            'shown': len(rows),
            'stats': {
                'total_ms': total_ms,
                'calls': sum(p['calls'] for p in all_patterns),
                'patterns': len(all_patterns),
                'repeating': sum(1 for p in all_patterns if p['repeats']),
                'slowest': max(all_patterns, key=lambda p: p['p95']) if all_patterns else None,
                'selects': sum(1 for p in all_patterns if p['type'] == 'SELECT'),
            },
            'tables': table_rows[:8],
            'more_tables': max(0, len(table_rows) - 8),
            'types': [{'name': t, 'count': sum(1 for p in all_patterns if p['type'] == t)} for t in SQL_TYPES],
            'f': {'q': q, 'type': typ, 'table': table, 'repeating': repeating, 'slow': slow, 'sort': sort},
            'slow_pattern_ms': sql_patterns.SLOW_PATTERN_MS,
            'p95_sample': sql_patterns.P95_SAMPLE,
            'detail': sql_patterns.pattern_detail(open_hash) if open_hash else None,
            'repeat_min': sql_patterns.REPEAT_MIN,
            'qs': qs,
            'open_hash': open_hash,
        }
        return render(request, _template(request, 'silk/sql_patterns.html', 'silk/inclusion/sql_patterns_split.html'), context)


class HotspotsView(View):
    """Lines of application code ranked by the database time they cause."""

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request):
        rows = sql_patterns.hotspots()
        top = rows[0]['total'] if rows else 1
        for r in rows:
            r['bar'] = max(2, round(r['total'] / top * 100)) if top else 2
            r['link'] = urlencode({'loc': r['code_location']})
        top3 = sum(r['share'] for r in rows[:3])
        loc = request.GET.get('loc', '')
        context = {
            'rows': rows[:200],
            'top3_share': top3,
            'count': len(rows),
            'detail': sql_patterns.hotspot_detail(loc) if loc else None,
            'open_loc': loc,
        }
        return render(request, _template(request, 'silk/hotspots.html', 'silk/inclusion/hotspots_split.html'), context)
