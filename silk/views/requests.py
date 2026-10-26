import json
import math

from django.db.models import Avg, Count, Q
from django.shortcuts import render
from django.template.context_processors import csrf
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk.auth import login_possibly_required, permissions_possibly_required
from silk.models import Request, Response, SQLQuery
from silk.request_filters import (
    TIME_RANGE_PRESETS,
    BaseFilter,
    FiltersManager,
    filters_from_request,
)
from silk.utils import prefs, quick_views
from silk.utils.aggregation import db_time_expr
from silk.utils.n_plus_one import fingerprint_query
from silk.utils.pagination import get_page

__author__ = 'mtford'

# Sort options: maps field key → display label + optional queryset transform
SORT_OPTIONS = {
    'start_time': {
        'label': 'Recent',
        'additional_query_filter': None,
    },
    'path': {
        'label': 'Path',
        'additional_query_filter': None,
    },
    'num_sql_queries': {
        'label': 'Num. Queries',
        'additional_query_filter': None,
    },
    'time_taken': {
        'label': 'Time',
        'additional_query_filter': lambda qs: qs.filter(time_taken__gte=0),
    },
    'db_time': {
        'label': 'DB Time',
        'additional_query_filter': lambda qs: qs.annotate(
            db_time=db_time_expr(qs.model)
        ).filter(db_time__gte=0),
    },
}

DEFAULT_SORT_LIST = [{'field': 'start_time', 'dir': 'DESC'}]
DEFAULT_PER_PAGE = 25
PER_PAGE_OPTIONS = [10, 25, 50, 100]
SESSION_KEY_FILTERS = 'request_filters'
SESSION_KEY_SORT = 'request_sort'


def _apply_sort(query_set, sort_list):
    """Apply a list of {field, dir} dicts as ORDER BY to *query_set*.

    Annotations are applied per-field (they're additive), but all ORDER BY
    columns are passed in a single .order_by() call so they compound rather
    than replace each other.
    """
    order_fields = []
    for item in sort_list:
        field = item.get('field', 'start_time')
        direction = item.get('dir', 'DESC')
        if field not in SORT_OPTIONS:
            continue
        opt = SORT_OPTIONS[field]
        if opt['additional_query_filter'] is not None:
            query_set = opt['additional_query_filter'](query_set)
        prefix = '-' if direction == 'DESC' else ''
        order_fields.append(f'{prefix}{field}')
    if order_fields:
        query_set = query_set.order_by(*order_fields)
    return query_set


class RequestsView(View):
    # Keep legacy attributes for backward compatibility
    show = PER_PAGE_OPTIONS
    default_show = DEFAULT_PER_PAGE

    order_by = {
        k: {'label': v['label'], 'additional_query_filter': v['additional_query_filter']}
        for k, v in SORT_OPTIONS.items()
    }
    order_dir = {
        'ASC': {'label': 'Ascending'},
        'DESC': {'label': 'Descending'},
    }
    view_style = {
        'card': {'label': 'Cards'},
        'row': {'label': 'Rows'},
    }
    default_order_by = 'start_time'
    default_order_dir = 'DESC'
    default_view_style = 'row'

    session_key_request_filters = SESSION_KEY_FILTERS
    filters_manager = FiltersManager(SESSION_KEY_FILTERS)

    @property
    def options_order_by(self):
        return [{'value': x, 'label': SORT_OPTIONS[x]['label']} for x in SORT_OPTIONS]

    @property
    def options_order_dir(self):
        return [{'value': x, 'label': self.order_dir[x]['label']} for x in self.order_dir]

    @property
    def options_view_style(self):
        return [{'value': x, 'label': self.view_style[x]['label']} for x in self.view_style]

    def _get_paths(self):
        return Request.objects.values_list('path', flat=True).order_by('path').distinct()

    def _get_views(self):
        return (
            Request.objects.values_list('view_name', flat=True)
            .exclude(Q(view_name='') | Q(view_name__isnull=True))
            .order_by('view_name')
            .distinct()
        )

    def _get_status_codes(self):
        return (
            Response.objects.values_list('status_code', flat=True)
            .order_by('status_code')
            .distinct()
        )

    METHOD_ORDER = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']

    def _get_methods(self):
        """Recorded methods, most common kinds first (GET, POST, ...), then any others alphabetically."""
        methods = Request.objects.values_list('method', flat=True).order_by('method').distinct()
        order = {m: i for i, m in enumerate(self.METHOD_ORDER)}
        return sorted(methods, key=lambda m: (order.get(m, len(order)), m))

    def _stats(self, qs, n1_min):
        """Headline numbers for the filtered set, computed in the database."""
        qs = qs.order_by()
        count = qs.count()
        if not count:
            return {'count': 0}
        agg = qs.aggregate(avg_ms=Avg('time_taken'), avg_queries=Avg('num_sql_queries'))
        times = qs.filter(time_taken__isnull=False).order_by('time_taken').values_list('time_taken', flat=True)
        timed = times.count()

        def pct(p):
            return times[min(timed - 1, int(p * timed))] if timed else None
        errors = qs.filter(response__status_code__gte=500).count()
        from silk.utils.summary_data import repeating_request_ids
        n1 = qs.filter(pk__in=repeating_request_ids(n1_min)).count()
        return {
            'n1': n1,
            'spark': self._spark(qs),
            'count': count,
            'p50': pct(0.5),
            'p95': pct(0.95),
            'avg_queries': agg['avg_queries'] or 0,
            'errors': errors,
            'error_rate': errors / count * 100,
        }

    SPARK_BUCKETS = 40
    SPARK_MAX = 20000

    def _spark(self, qs):
        """SVG path (120x28 box) of request counts over time for the filtered set, newest SPARK_MAX."""
        times = list(qs.order_by('-start_time').values_list('start_time', flat=True)[:self.SPARK_MAX])
        if len(times) < 2:
            return ''
        lo, hi = times[-1], times[0]
        span = (hi - lo).total_seconds() or 1
        counts = [0] * self.SPARK_BUCKETS
        for t in times:
            counts[min(self.SPARK_BUCKETS - 1, int((t - lo).total_seconds() / span * self.SPARK_BUCKETS))] += 1
        top = max(counts) or 1
        step = 120 / (self.SPARK_BUCKETS - 1)
        return ' '.join(f"{'L' if i else 'M'}{i * step:.1f} {26 - c / top * 24:.1f}" for i, c in enumerate(counts))

    def _method_chips(self):
        """Recorded methods with their request counts, common methods first."""
        counts = dict(Request.objects.order_by().values_list('method').annotate(n=Count('id')))
        order = {m: i for i, m in enumerate(self.METHOD_ORDER)}
        return [{'method': m, 'count': counts[m]} for m in sorted(counts, key=lambda m: (order.get(m, len(order)), m))]

    def _status_classes(self, raw_filters):
        """Status-code chips (2xx..5xx): which recorded codes belong to each, and whether it is on."""
        selected = set()
        if raw_filters.get('status_code'):
            try:
                selected = set(json.loads(raw_filters['status_code']['value']))
            except (TypeError, ValueError, KeyError):
                selected = set()
        recorded = dict(Response.objects.order_by().values_list('status_code').annotate(n=Count('id')))
        classes = []
        for digit in '2345':
            codes = sorted(c for c in recorded if str(c).startswith(digit))
            if codes:
                classes.append({'label': digit + 'xx', 'digit': digit, 'codes': json.dumps(codes),
                                'count': sum(recorded[c] for c in codes),
                                'active': bool(codes) and set(codes) <= selected})
        return classes

    def _get_sort_list(self, request):
        """Return the current sort list from session, falling back to defaults."""
        if hasattr(request, 'session'):
            return request.session.get(SESSION_KEY_SORT, DEFAULT_SORT_LIST)
        return DEFAULT_SORT_LIST

    def _save_sort_list(self, request, sort_list):
        if hasattr(request, 'session'):
            request.session[SESSION_KEY_SORT] = sort_list

    # Sentinel so we can distinguish "not passed" from explicit None
    _SHOW_NOT_SET = object()

    def _get_objects(self, show=_SHOW_NOT_SET, order_by=None, order_dir=None, path=None, filters=None, sort_list=None, request=None):
        """Build and return a queryset (or sliced queryset for backward compat).

        When *show* is not passed, defaults to self.default_show and slices the
        queryset — preserving the original API so existing tests still pass.
        Pass show=None explicitly to get the full (unsliced) queryset for the paginator.
        """
        if not filters:
            filters = []
        query_set = Request.objects.all()

        # Determine sort
        if sort_list:
            query_set = _apply_sort(query_set, sort_list)
        else:
            if not order_by:
                order_by = self.default_order_by
            if not order_dir:
                order_dir = self.default_order_dir
            if order_by not in SORT_OPTIONS:
                raise RuntimeError('Unknown order_by: "%s"' % order_by)
            query_set = _apply_sort(query_set, [{'field': order_by, 'dir': order_dir}])

        if path:
            query_set = query_set.filter(path=path)
        for f in filters:
            query_set = f.contribute_to_query_set(query_set)
            query_set = query_set.filter(f)

        # Backward-compatible slicing: if show was not explicitly passed, default to default_show
        if show is self._SHOW_NOT_SET:
            show = self.default_show
        if show is not None:
            return query_set[:show]
        return query_set

    def _create_context(self, request):
        raw_filters = self.filters_manager.get(request).copy()
        show = raw_filters.pop('show', self.default_show)
        order_by = raw_filters.pop('order_by', self.default_order_by)
        order_dir = raw_filters.pop('order_dir', self.default_order_dir)
        view_style = raw_filters.pop('view_style', self.default_view_style)

        if show:
            show = int(show)
        per_page = show or DEFAULT_PER_PAGE

        path = request.GET.get('path', None)
        sort_list = self._get_sort_list(request)
        th = prefs.thresholds(request)
        # The N+1 filter always uses the viewer's current repeat count from Settings.
        if raw_filters.get('nplusone', {}).get('value'):
            raw_filters['nplusone'] = {**raw_filters['nplusone'], 'value': str(th['n1_min'])}

        qs = self._get_objects(
            show=None,  # paginator handles limiting
            order_by=order_by,
            order_dir=order_dir,
            path=path,
            filters=[BaseFilter.from_dict(x) for _, x in raw_filters.items()],
            sort_list=sort_list,
        )

        stats = self._stats(qs, th['n1_min'])
        # One query for the page: join the response (status code) and compute DB
        # time as a subquery, instead of two extra queries per row.
        page_obj = get_page(request, qs.select_related('response').annotate(db_ms=db_time_expr(Request)), per_page)

        # Batch N+1 detection for the current page (1 extra DB query)
        page_request_ids = [r.pk for r in page_obj.object_list]
        has_n1_on_page = False
        if page_request_ids:
            sql_rows = SQLQuery.objects.filter(
                request_id__in=page_request_ids
            ).values('request_id', 'query')
            # Group by request, fingerprint, count occurrences
            buckets = {}  # request_id -> fingerprint -> count
            for row in sql_rows:
                rid = row['request_id']
                fp = fingerprint_query(row['query'])
                buckets.setdefault(rid, {}).setdefault(fp, 0)
                buckets[rid][fp] += 1
            n1_request_ids = {
                rid for rid, fps in buckets.items()
                if any(cnt >= th['n1_min'] for cnt in fps.values())
            }
            for r in page_obj.object_list:
                r.has_n1 = r.pk in n1_request_ids
            has_n1_on_page = bool(n1_request_ids)

        # Time bar (square-root scale so fast requests stay visible) and speed tier per row.
        page_max = max([r.time_taken or 0 for r in page_obj.object_list] + [1])
        for r in page_obj.object_list:
            ms = r.time_taken or 0
            r.bar_pct = max(2, round(math.sqrt(ms / page_max) * 100))
            r.tier = prefs.tier(ms, th)

        selected_methods = []
        if raw_filters.get('method'):
            try:
                selected_methods = json.loads(raw_filters['method']['value'])
            except (TypeError, ValueError, KeyError):
                selected_methods = []

        # The common five stay in the chip row; HEAD, OPTIONS and the rest sit in More.
        method_chips = self._method_chips()
        main_methods = [m for m in method_chips if m['method'] in self.METHOD_ORDER[:5]]
        other_methods = [m for m in method_chips if m not in main_methods]
        more_active = sum(1 for k in ('seconds', 'numqueriesfilter') if raw_filters.get(k, {}).get('value'))
        more_active += sum(1 for m in other_methods if m['method'] in selected_methods)

        context = {
            'show': show,
            'per_page': per_page,
            'order_by': order_by,
            'order_dir': order_dir,
            'view_style': view_style,
            'request': request,
            'options_show': self.show,
            'options_order_by': self.options_order_by,
            'options_order_dir': self.options_order_dir,
            'options_view_style': self.options_view_style,
            'options_paths': self._get_paths(),
            'options_status_codes': self._get_status_codes(),
            'options_methods': self._get_methods(),
            'method_chips': main_methods,
            'other_method_chips': other_methods,
            'more_active': more_active,
            'view_names': self._get_views(),
            'filters': raw_filters,
            'sort_list': sort_list,
            'sort_fields_used': [item['field'] for item in sort_list],
            'sort_options': [
                {'value': k, 'label': v['label']} for k, v in SORT_OPTIONS.items()
            ],
            'time_presets': [
                {'key': k, 'seconds': v, 'label': k} for k, v in TIME_RANGE_PRESETS.items()
            ],
            'page_obj': page_obj,
            'thresholds': th,
            'stats': stats,
            'selected_methods': selected_methods,
            'current_sort': sort_list[0] if sort_list else DEFAULT_SORT_LIST[0],
            'status_classes': self._status_classes(raw_filters),
            'results': page_obj.object_list,  # backward compat
            'has_n1_on_page': has_n1_on_page,
        }
        context.update(csrf(request))
        if path:
            context['path'] = path
        return context

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request):
        # Read sort_criteria JSON from URL param (enables shared URLs to restore sort state)
        if request.GET.get('sort_criteria'):
            try:
                sort_list = json.loads(request.GET['sort_criteria'])
                if isinstance(sort_list, list) and sort_list:
                    self._save_sort_list(request, sort_list)
            except (ValueError, TypeError):
                pass
        # Handle sort_criteria from GET (backward compat: order_by / order_dir)
        elif request.GET.get('order_by') or request.GET.get('order_dir'):
            ob = request.GET.get('order_by', self.default_order_by)
            od = request.GET.get('order_dir', self.default_order_dir)
            self._save_sort_list(request, [{'field': ob, 'dir': od}])

        if request.GET:
            filters = {
                **self.filters_manager.get(request),
                **{
                    k: v
                    for k, v in request.GET.items()
                    if k in ['show', 'order_by', 'order_dir', 'view_style']
                },
            }
            # per_page in URL is an alias for show (enables shared URLs to restore page size)
            if 'per_page' in request.GET and 'show' not in request.GET:
                filters['show'] = request.GET['per_page']
            # ?quick= from the sidebar quick views replaces the current filters.
            if request.GET.get('quick') in quick_views.QUICK_VIEWS:
                filters = {k: v for k, v in filters.items() if k in ('show', 'view_style')}
                filters.update(quick_views.quick_filters(request.GET['quick'], prefs.thresholds(request)['slow_ms']))
            # ?q= from the top bar search sets the free-text search.
            if 'q' in request.GET:
                from silk.request_filters import FilterValidationError, SearchFilter
                filters.pop('search', None)
                try:
                    filters['search'] = SearchFilter(request.GET['q']).as_dict()
                except FilterValidationError:
                    pass
            # ?view= from N+1 suspects link — save as a proper ViewNameFilter in session
            if request.GET.get('view'):
                from silk.request_filters import ViewNameFilter
                filters['view'] = ViewNameFilter(request.GET['view']).as_dict()
            # ?path= from hot-path links on summary page — save as a MultiPathFilter in session
            if request.GET.get('path'):
                from silk.request_filters import MultiPathFilter
                try:
                    filters['path'] = MultiPathFilter(request.GET['path']).as_dict()
                except Exception:
                    pass
            self.filters_manager.save(request, filters)
        return self._render(request)

    def _render(self, request):
        # htmx asks for the results region only; everything else stays on the page.
        template = 'silk/inclusion/requests_results.html' if request.headers.get('HX-Request') else 'silk/requests.html'
        return render(request, template, self._create_context(request))

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def post(self, request):
        previous_session = self.filters_manager.get(request)

        # Handle sort_criteria update from POST
        sort_criteria_raw = request.POST.get('sort_criteria', '')
        if sort_criteria_raw:
            try:
                sort_list = json.loads(sort_criteria_raw)
                if isinstance(sort_list, list):
                    self._save_sort_list(
                        request, sort_list if sort_list else DEFAULT_SORT_LIST
                    )
            except (ValueError, TypeError):
                pass

        # Detect whether this POST came from the filter form or the sort/toolbar form.
        # The filter form always includes at least one filter-*-typ hidden field.
        # The sort/toolbar form only contains sort_criteria, show, view_style.
        is_filter_submit = any(k.startswith('filter-') for k in request.POST)

        if 'clear_filters' in request.POST:
            filters = {k: v for k, v in previous_session.items() if k in ['show', 'view_style']}
            self.filters_manager.save(request, filters)
        elif is_filter_submit:
            # Full filter form submitted — replace filter set with what the form says.
            filters = {
                **{k: v for k, v in previous_session.items() if k in ['show', 'order_by', 'order_dir', 'view_style']},
                **{ident: f.as_dict() for ident, f in filters_from_request(request).items()},
            }
            self.filters_manager.save(request, filters)
        else:
            # Sort / toolbar form — only update show/view_style, keep all existing filters.
            non_filter_keys = ['show', 'order_by', 'order_dir', 'view_style']
            updated = {k: v for k, v in request.POST.items() if k in non_filter_keys}
            filters = {**previous_session, **updated}
            self.filters_manager.save(request, filters)

        return self._render(request)
