import json

from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk.auth import login_possibly_required, permissions_possibly_required
from silk.code_generation.curl import curl_cmd
from silk.code_generation.django_test_client import gen
from silk.models import Request, SQLQuery
from silk.utils import prefs
from silk.utils.compare import endpoint_key, endpoint_q
from silk.utils.insights import request_insights
from silk.utils.n_plus_one import detect_n_plus_one, pattern_hash
from silk.utils.sql_patterns import sql_table, sql_type

PANEL_QUERIES = 100   # queries listed in the side panel's SQL tab


def panel_sql(silk_request, queries, flagged_ids, repeat_min):
    """The panel's SQL tab: each query placed on the request's timeline, and the same queries grouped by shape.

    Timeline bars start where the query started and are as long as it ran, both
    as a share of the request. If any start time falls outside the request (bad
    or clock-skewed data), the bars fall back to durations side by side.
    """
    start, total = silk_request.start_time, silk_request.time_taken or 0
    rows = []
    for q in queries:
        offset = (q.start_time - start).total_seconds() * 1000 if q.start_time and start else None
        rows.append({'q': q, 'offset': offset, 'ms': q.time_taken or 0, 'type': sql_type(q.query),
                     'table': sql_table(q.query), 'repeated': q.pk in flagged_ids})
    timeline = bool(rows) and all(r['offset'] is not None and r['offset'] >= 0 for r in rows)
    span = max([total] + [r['offset'] + r['ms'] for r in rows] if timeline else [1] + [r['ms'] for r in rows]) or 1
    for r in rows:
        left = min(r['offset'] / span * 100, 99.4) if timeline else 0
        r['left'] = round(left, 2)
        r['width'] = round(min(max(r['ms'] / span * 100, 0.6), 100 - left), 2)

    groups = {}
    for r in rows:
        key = r['q'].pattern_hash or pattern_hash(r['q'].query)
        g = groups.setdefault(key, {'hash': key, 'n': 0, 'ms': 0, 'q': r['q'], 'type': r['type'], 'table': r['table']})
        g['n'] += 1
        g['ms'] += r['ms']
    grouped = sorted(groups.values(), key=lambda g: g['ms'], reverse=True)
    top = max([g['ms'] for g in grouped] + [1]) or 1
    for g in grouped:
        g['repeated'] = g['n'] >= repeat_min
        g['width'] = round(max(g['ms'] / top * 100, 0.6), 2)
    return {'rows': rows, 'timeline': timeline, 'span_ms': span if timeline else None, 'groups': grouped}


class RequestView(View):

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request, request_id):
        silk_request = get_object_or_404(Request, pk=request_id)
        query_params = None
        if silk_request.query_params:
            query_params = json.loads(silk_request.query_params)

        context = {
            'silk_request': silk_request,
            'query_params': json.dumps(query_params, sort_keys=True, indent=4) if query_params else None,
            'request': request
        }

        if len(silk_request.raw_body) < 20000:  # Don't do this for large request
            body = silk_request.raw_body
            try:
                body = json.loads(body)  # Incase encoded as JSON
            except (ValueError, TypeError):
                pass
            context['curl'] = curl_cmd(url=request.build_absolute_uri(silk_request.path),
                                       method=silk_request.method,
                                       query_params=query_params,
                                       body=body,
                                       content_type=silk_request.content_type)
            context['client'] = gen(path=silk_request.path,
                                    method=silk_request.method,
                                    query_params=query_params,
                                    data=body,
                                    content_type=silk_request.content_type)

        all_queries = list(SQLQuery.objects.filter(request=silk_request)) if silk_request.num_sql_queries > 0 else []
        n1_min = prefs.thresholds(request)['n1_min']
        if all_queries:
            context['n_plus_one'] = detect_n_plus_one(all_queries, n1_min)
        context['insights'] = request_insights(silk_request, all_queries, n1_min)
        context['previous_id'] = (Request.objects
                                  .filter(endpoint_q(endpoint_key(silk_request.view_name, silk_request.path)),
                                          start_time__lt=silk_request.start_time)
                                  .order_by('-start_time').values_list('pk', flat=True).first())

        # The requests list opens a request in a side panel through htmx; a normal visit gets the full page.
        template = 'silk/request.html'
        if request.headers.get('HX-Request'):
            template = 'silk/inclusion/request_panel.html'
            queries = sorted(all_queries, key=lambda q: (q.start_time is None, q.start_time or 0, q.pk))[:PANEL_QUERIES]
            context['queries'] = queries
            flagged = context['n_plus_one'].flagged_query_ids if all_queries else set()
            context['sql'] = panel_sql(silk_request, queries, flagged, n1_min)
            context['profiles'] = list(silk_request.profile_set.order_by('-time_taken')[:50])
        return render(request, template, context)
