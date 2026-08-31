import json

from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import TruncHour, TruncDay
from django.shortcuts import render
from django.template.context_processors import csrf
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk import models
from silk.auth import login_possibly_required, permissions_possibly_required
from silk.request_filters import (
    BaseFilter,
    FiltersManager,
    TIME_RANGE_PRESETS,
    filters_from_request,
)


PERCENTILES = [25, 50, 75, 95, 99]


def _percentiles(queryset, field, percentiles=PERCENTILES):
    """Linear-interpolation percentiles computed with COUNT plus OFFSET/LIMIT
    lookups, so the value column is never materialised in Python. Works on
    SQLite/PG/MySQL."""
    values = queryset.order_by(field).values_list(field, flat=True)
    n = values.count()
    if n == 0:
        return {p: 0.0 for p in percentiles}
    result = {}
    for p in percentiles:
        idx = (p / 100.0) * (n - 1)
        lo = int(idx)
        frac = idx - lo
        window = list(values[lo:lo + 2])
        if frac and len(window) > 1:
            value = window[0] * (1 - frac) + window[1] * frac
        else:
            value = window[0]
        result[p] = round(float(value), 2)
    return result


def _bucket_counts(queryset, field, buckets):
    """Count rows per [lo, hi) bucket in a single aggregate query instead of
    fetching every value. `buckets` is a list of (label, lo, hi) with None
    meaning unbounded."""
    aggregates = {}
    for i, (_, lo, hi) in enumerate(buckets):
        condition = Q()
        if lo is not None:
            condition &= Q(**{f'{field}__gte': lo})
        if hi is not None:
            condition &= Q(**{f'{field}__lt': hi})
        aggregates[f'bucket_{i}'] = Count('pk', filter=condition)
    counts = queryset.aggregate(**aggregates)
    return [
        {'label': label, 'count': counts[f'bucket_{i}']}
        for i, (label, _, _) in enumerate(buckets)
    ]


def _top_request(rows):
    """Materialise the first row of a ``values('pk')`` aggregate queryset as a
    Request, with the aggregate attached as ``.t`` for the template.

    Aggregating over ``values('pk')`` keeps the GROUP BY down to the primary
    key. Annotating whole Request rows instead would group by every column,
    including the NCLOB ones on Oracle, which that backend rejects. See
    silk/utils/aggregation.py.
    """
    row = next(iter(rows), None)
    if row is None:
        return None
    request = models.Request.objects.get(pk=row['pk'])
    request.t = row['t']
    return request


class SummaryView(View):
    filters_key = 'summary_filters'
    filters_manager = FiltersManager(filters_key)

    def _avg_num_queries(self, filters):
        queries__aggregate = (
            models.Request.objects.filter(*filters)
            .values('pk')
            .annotate(num_queries=Count('queries'))
            .aggregate(num=Avg('num_queries'))
        )
        return queries__aggregate['num']

    def _avg_time_spent_on_queries(self, filters):
        taken__aggregate = (
            models.Request.objects.filter(*filters)
            .values('pk')
            .annotate(time_spent=Sum('queries__time_taken'))
            .aggregate(num=Avg('time_spent'))
        )
        return taken__aggregate['num']

    def _avg_overall_time(self, filters):
        # Per-request Sum('time_taken') is just the row's own time_taken, so
        # average the column directly and skip the grouping entirely.
        taken__aggregate = models.Request.objects.filter(*filters).aggregate(num=Avg('time_taken'))
        return taken__aggregate['num']

    # TODO: Find a more efficient way to do this. Currently has to go to DB num. views + 1 times and is prob quite expensive
    def _longest_query_by_view(self, filters):
        values_list = models.Request.objects.filter(*filters).values_list("view_name").annotate(max=Max('time_taken')).filter(max__isnull=False).order_by('-max')[:5]
        requests = []
        for view_name, _ in values_list:
            request = models.Request.objects.filter(view_name=view_name, *filters).filter(time_taken__isnull=False).order_by('-time_taken')[0]
            requests.append(request)
        return sorted(requests, key=lambda item: item.time_taken, reverse=True)

    def _time_spent_in_db_by_view(self, filters):
        values_list = models.Request.objects.filter(*filters).values_list('view_name').annotate(t=Sum('queries__time_taken')).filter(t__gte=0).order_by('-t')[:5]
        requests = []
        for view, _ in values_list:
            request = _top_request(
                models.Request.objects.filter(view_name=view, *filters)
                .values('pk')
                .annotate(t=Sum('queries__time_taken'))
                .filter(t__isnull=False)
                .order_by('-t')[:1]
            )
            if request is not None:
                requests.append(request)
        return sorted(requests, key=lambda item: item.t, reverse=True)

    def _request_time_percentiles(self, filters):
        queryset = models.Request.objects.filter(*filters).filter(time_taken__isnull=False)
        return _percentiles(queryset, 'time_taken')

    def _sql_time_percentiles(self, filters):
        requests = models.Request.objects.filter(*filters)
        queryset = models.SQLQuery.objects.filter(
            request__in=requests, time_taken__isnull=False,
        )
        return _percentiles(queryset, 'time_taken')

    def _request_timeline(self, filters):
        """Hourly (or daily) request counts for the activity chart."""
        qs = models.Request.objects.filter(*filters)
        agg = qs.aggregate(min_t=Min('start_time'), max_t=Max('start_time'))
        if not agg['min_t']:
            return []
        span_hours = (agg['max_t'] - agg['min_t']).total_seconds() / 3600
        trunc = TruncDay if span_hours > 72 else TruncHour
        buckets = (
            qs.annotate(bucket=trunc('start_time'))
            .values('bucket')
            .annotate(count=Count('id'))
            .order_by('bucket')
        )
        return [{'t': b['bucket'].isoformat(), 'count': b['count']} for b in buckets]

    def _status_distribution(self, filters):
        """Count requests by HTTP status class."""
        requests = models.Request.objects.filter(*filters)
        rows = (
            models.Response.objects
            .filter(request__in=requests, status_code__isnull=False)
            .values('status_code')
            .annotate(count=Count('id'))
        )
        buckets = {'2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0}
        for row in rows:
            sc = row['status_code']
            if 200 <= sc < 300:
                buckets['2xx'] += row['count']
            elif 300 <= sc < 400:
                buckets['3xx'] += row['count']
            elif 400 <= sc < 500:
                buckets['4xx'] += row['count']
            elif sc >= 500:
                buckets['5xx'] += row['count']
        return buckets

    def _method_distribution(self, filters):
        """Count requests by HTTP method, sorted descending."""
        rows = (
            models.Request.objects.filter(*filters)
            .values('method')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        return [{'method': r['method'], 'count': r['count']} for r in rows]

    def _response_time_histogram(self, filters):
        """Bucket response times into 6 fixed ranges."""
        queryset = models.Request.objects.filter(*filters).filter(
            time_taken__isnull=False, time_taken__gte=0,
        )
        return _bucket_counts(queryset, 'time_taken', [
            ('<50ms',     None, 50),
            ('50-100ms',  50,   100),
            ('100-200ms', 100,  200),
            ('200-500ms', 200,  500),
            ('500ms-1s',  500,  1000),
            ('>1s',       1000, None),
        ])

    def _num_queries_by_view(self, filters):
        queryset = models.Request.objects.filter(*filters).values_list('view_name').annotate(t=Count('queries')).order_by('-t')[:5]
        views = [r[0] for r in queryset[:6]]
        requests = []
        for view in views:
            request = _top_request(
                models.Request.objects.filter(view_name=view, *filters)
                .values('pk')
                .annotate(t=Count('queries'))
                .order_by('-t')[:1]
            )
            if request is not None:
                requests.append(request)
        return sorted(requests, key=lambda item: item.t, reverse=True)

    def _hot_paths(self, filters):
        """Top 5 endpoints by optimization impact (request_count × avg_time_taken)."""
        rows = list(
            models.Request.objects.filter(*filters)
            .filter(time_taken__isnull=False)
            .values('path')
            .annotate(count=Count('id'), avg_time=Avg('time_taken'))
        )
        rows.sort(key=lambda r: r['count'] * r['avg_time'], reverse=True)
        return rows[:5]

    def _n1_suspects(self, filters):
        """Top 5 view names with highest average SQL query count — likely N+1 candidates."""
        rows = (
            models.Request.objects.filter(*filters)
            .filter(view_name__isnull=False, num_sql_queries__gt=0)
            .exclude(view_name='')
            .values('view_name')
            .annotate(avg_queries=Avg('num_sql_queries'), count=Count('id'))
            .filter(count__gte=2)
            .order_by('-avg_queries')[:5]
        )
        return list(rows)

    def _query_count_histogram(self, filters):
        """Bucket requests by the number of SQL queries they fired."""
        queryset = models.Request.objects.filter(*filters)
        return _bucket_counts(queryset, 'num_sql_queries', [
            ('0',     None, 1),
            ('1–5',   1,    6),
            ('6–10',  6,    11),
            ('11–25', 11,   26),
            ('26–50', 26,   51),
            ('>50',   51,   None),
        ])

    def _create_context(self, request):
        raw_filters = self.filters_manager.get(request)
        filters = [BaseFilter.from_dict(filter_d) for _, filter_d in raw_filters.items()]
        avg_num_q = self._avg_num_queries(filters)
        avg_db_time = self._avg_time_spent_on_queries(filters) or 0
        avg_total_time = self._avg_overall_time(filters) or 0
        db_pressure = round(avg_db_time / avg_total_time * 100, 1) if avg_total_time > 0 else 0
        num_requests = models.Request.objects.filter(*filters).count()
        active_preset = raw_filters.get('time_preset', {}).get('value')
        request_percentiles = self._request_time_percentiles(filters)
        sql_percentiles = self._sql_time_percentiles(filters)
        c = {
            'request': request,
            'num_requests': num_requests,
            'num_profiles': models.Profile.objects.filter(*filters).count(),
            'avg_num_queries': avg_num_q,
            'avg_time_spent_on_queries': avg_db_time,
            'avg_overall_time': avg_total_time,
            'db_pressure': db_pressure,
            'longest_queries_by_view': self._longest_query_by_view(filters),
            'most_time_spent_in_db': self._time_spent_in_db_by_view(filters),
            'most_queries': self._num_queries_by_view(filters),
            'hot_paths': self._hot_paths(filters),
            'n1_suspects': self._n1_suspects(filters),
            'filters': raw_filters,
            'has_data': num_requests > 0,
            'time_presets': [
                {'key': k, 'seconds': v, 'label': k} for k, v in TIME_RANGE_PRESETS.items()
            ],
            'active_preset': active_preset,
            'request_percentiles': request_percentiles,
            'sql_percentiles': sql_percentiles,
            'chart_json': json.dumps({
                'request': request_percentiles,
                'sql': sql_percentiles,
                'timeline': self._request_timeline(filters),
                'status': self._status_distribution(filters),
                'methods': self._method_distribution(filters),
                'rt_hist': self._response_time_histogram(filters),
                'query_hist': self._query_count_histogram(filters),
            }),
        }
        c.update(csrf(request))
        return c

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request):
        c = self._create_context(request)
        return render(request, 'silk/summary.html', c)

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def post(self, request):
        # Handle time preset shortcut
        preset_key = request.POST.get('time_preset', '')
        if preset_key in TIME_RANGE_PRESETS:
            from silk.request_filters import SecondsFilter
            seconds = TIME_RANGE_PRESETS[preset_key]
            f = SecondsFilter(seconds)
            filters = {'time_preset': f.as_dict()}
        elif 'clear_filters' in request.POST:
            filters = {}
        else:
            filters = {ident: f.as_dict() for ident, f in filters_from_request(request).items()}
        self.filters_manager.save(request, filters)
        return render(request, 'silk/summary.html', self._create_context(request))
