import json

from django.db.models import Avg, Count, Max, Min, Sum
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


def _percentile(sorted_data, p):
    """Linear-interpolation percentile (stdlib only, works on SQLite/PG/MySQL)."""
    n = len(sorted_data)
    if n == 0:
        return 0.0
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    frac = idx - lo
    if hi >= n:
        return float(sorted_data[-1])
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


class SummaryView(View):
    filters_key = 'summary_filters'
    filters_manager = FiltersManager(filters_key)

    def _avg_num_queries(self, filters):
        queries__aggregate = models.Request.objects.filter(*filters).annotate(num_queries=Count('queries')).aggregate(num=Avg('num_queries'))
        return queries__aggregate['num']

    def _avg_time_spent_on_queries(self, filters):
        taken__aggregate = models.Request.objects.filter(*filters).annotate(time_spent=Sum('queries__time_taken')).aggregate(num=Avg('time_spent'))
        return taken__aggregate['num']

    def _avg_overall_time(self, filters):
        taken__aggregate = models.Request.objects.filter(*filters).annotate(time_spent=Sum('time_taken')).aggregate(num=Avg('time_spent'))
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
            r = models.Request.objects.filter(view_name=view, *filters).annotate(t=Sum('queries__time_taken')).filter(t__isnull=False).order_by('-t')[0]
            requests.append(r)
        return sorted(requests, key=lambda item: item.t, reverse=True)

    def _request_time_percentiles(self, filters):
        times = list(
            models.Request.objects.filter(*filters)
            .filter(time_taken__isnull=False)
            .order_by('time_taken')
            .values_list('time_taken', flat=True)
        )
        return {p: round(_percentile(times, p), 2) for p in [25, 50, 75, 95, 99]}

    def _sql_time_percentiles(self, filters):
        pks = list(models.Request.objects.filter(*filters).values_list('pk', flat=True))
        if not pks:
            return {p: 0.0 for p in [25, 50, 75, 95, 99]}
        times = list(
            models.SQLQuery.objects.filter(request_id__in=pks, time_taken__isnull=False)
            .order_by('time_taken')
            .values_list('time_taken', flat=True)
        )
        return {p: round(_percentile(times, p), 2) for p in [25, 50, 75, 95, 99]}

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
        request_pks = list(models.Request.objects.filter(*filters).values_list('pk', flat=True))
        if not request_pks:
            return {'2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0}
        rows = (
            models.Response.objects
            .filter(request_id__in=request_pks, status_code__isnull=False)
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
        times = list(
            models.Request.objects.filter(*filters)
            .filter(time_taken__isnull=False, time_taken__gte=0)
            .values_list('time_taken', flat=True)
        )
        buckets = [
            {'label': '<50ms',    'max': 50,   'count': 0},
            {'label': '50-100ms', 'max': 100,  'count': 0},
            {'label': '100-200ms','max': 200,  'count': 0},
            {'label': '200-500ms','max': 500,  'count': 0},
            {'label': '500ms-1s', 'max': 1000, 'count': 0},
            {'label': '>1s',      'max': None,  'count': 0},
        ]
        prev = 0
        for t in times:
            for b in buckets:
                if b['max'] is None or t < b['max']:
                    b['count'] += 1
                    break
        return [{'label': b['label'], 'count': b['count']} for b in buckets]

    def _num_queries_by_view(self, filters):
        queryset = models.Request.objects.filter(*filters).values_list('view_name').annotate(t=Count('queries')).order_by('-t')[:5]
        views = [r[0] for r in queryset[:6]]
        requests = []
        for view in views:
            try:
                r = models.Request.objects.filter(view_name=view, *filters).annotate(t=Count('queries')).order_by('-t')[0]
                requests.append(r)
            except IndexError:
                pass
        return sorted(requests, key=lambda item: item.t, reverse=True)

    def _create_context(self, request):
        raw_filters = self.filters_manager.get(request)
        filters = [BaseFilter.from_dict(filter_d) for _, filter_d in raw_filters.items()]
        avg_overall_time = self._avg_num_queries(filters)
        num_requests = models.Request.objects.filter(*filters).count()
        active_preset = raw_filters.get('time_preset', {}).get('value')
        request_percentiles = self._request_time_percentiles(filters)
        sql_percentiles = self._sql_time_percentiles(filters)
        c = {
            'request': request,
            'num_requests': num_requests,
            'num_profiles': models.Profile.objects.filter(*filters).count(),
            'avg_num_queries': avg_overall_time,
            'avg_time_spent_on_queries': self._avg_time_spent_on_queries(filters),
            'avg_overall_time': self._avg_overall_time(filters),
            'longest_queries_by_view': self._longest_query_by_view(filters),
            'most_time_spent_in_db': self._time_spent_in_db_by_view(filters),
            'most_queries': self._num_queries_by_view(filters),
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
