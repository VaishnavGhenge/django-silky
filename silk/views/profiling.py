import uuid

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.template.context_processors import csrf
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk.auth import login_possibly_required, permissions_possibly_required
from silk.models import Profile, Request
from silk.request_filters import BaseFilter, FiltersManager, TIME_RANGE_PRESETS, filters_from_request
from silk.utils import profiling_data
from silk.utils.pagination import get_page


def _is_uuid(value):
    try:
        uuid.UUID(value)
    except (TypeError, ValueError):
        return False
    return True


class ProfilingView(View):
    show = [5, 10, 25, 100, 250]
    default_show = 25
    order_by = ['Recent',
                'Name',
                'Function Name',
                'Num. Queries',
                'Time',
                'Time on queries']
    defualt_order_by = 'Recent'
    session_key_profile_filters = 'session_key_profile_filters'
    filters_manager = FiltersManager(session_key_profile_filters)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _get_distinct_values(self, field, silk_request):
        if silk_request:
            query_set = Profile.objects.filter(request=silk_request)
        else:
            query_set = Profile.objects.all()
        function_names = [x[field] for x in query_set.values(field).distinct()]
        # Ensure top, default option is ''
        try:
            function_names.remove('')
        except ValueError:
            pass
        return [''] + function_names

    def _get_function_names(self, silk_request=None):
        return self._get_distinct_values('func_name', silk_request)

    def _get_names(self, silk_request=None):
        return self._get_distinct_values('name', silk_request)

    def _get_objects(self, show=None, order_by=None, name=None, func_name=None, silk_request=None, filters=None):
        if not filters:
            filters = []
        if not show:
            show = self.default_show
        manager = Profile.objects
        if silk_request:
            query_set = manager.filter(request=silk_request)
        else:
            query_set = manager.all()
        if not order_by:
            order_by = self.defualt_order_by
        if order_by == 'Recent':
            query_set = query_set.order_by('-start_time')
        elif order_by == 'Name':
            query_set = query_set.order_by('-name')
        elif order_by == 'Function Name':
            query_set = query_set.order_by('-func_name')
        elif order_by == 'Num. Queries':
            query_set = query_set.annotate(num_queries=Count('queries')).order_by('-num_queries')
        elif order_by == 'Time':
            query_set = query_set.order_by('-time_taken')
        elif order_by == 'Time on queries':
            query_set = query_set.annotate(db_time=Sum('queries__time_taken')).order_by('-db_time')
        elif order_by:
            raise RuntimeError('Unknown order_by: "%s"' % order_by)
        if func_name:
            query_set = query_set.filter(func_name=func_name)
        if name:
            query_set = query_set.filter(name=name)
        for f in filters:
            query_set = f.contribute_to_query_set(query_set)
            query_set = query_set.filter(f)
        if show is not None:
            return list(query_set[:show])
        return query_set

    def _create_context(self, request, *args, **kwargs):
        request_id = kwargs.get('request_id')
        if request_id:
            silk_request = get_object_or_404(Request, pk=request_id)
        else:
            silk_request = None
        show_param = request.GET.get('show')
        has_session = hasattr(request, 'session')
        if show_param is not None:
            try:
                show = int(show_param)
            except (TypeError, ValueError):
                show = self.default_show
            if has_session:
                request.session['silk_profiling_show'] = show
        else:
            try:
                saved = request.session.get('silk_profiling_show', self.default_show) if has_session else self.default_show
                show = int(saved)
            except (TypeError, ValueError):
                show = self.default_show
        order_by = request.GET.get('order_by', self.defualt_order_by)
        func_name = request.GET.get('func_name', None)
        name = request.GET.get('name', None)
        filters = self.filters_manager.get(request)
        context = {
            'show': show,
            'order_by': order_by,
            'request': request,
            'func_name': func_name,
            'options_show': self.show,
            'options_order_by': self.order_by,
            'options_func_names': self._get_function_names(silk_request),
            'options_names': self._get_names(silk_request),
            'filters': filters
        }
        context.update(csrf(request))
        if silk_request:
            context['silk_request'] = silk_request
        if func_name:
            context['func_name'] = func_name
        if name:
            context['name'] = name
        qs = self._get_objects(show=None,
                              order_by=order_by,
                              func_name=func_name,
                              silk_request=silk_request,
                              name=name,
                              filters=[BaseFilter.from_dict(x) for _, x in filters.items()])
        page_obj = get_page(request, qs, show)
        context['page_obj'] = page_obj
        context['results'] = page_obj.object_list
        context['time_presets'] = [
            {'key': k, 'seconds': v, 'label': k} for k, v in TIME_RANGE_PRESETS.items()
        ]
        # Blocks sort themselves; 'Recent' keeps order_by annotations out of their GROUP BY.
        base = Profile.objects.filter(request=silk_request) if silk_request else Profile.objects.all()
        if func_name:
            base = base.filter(func_name=func_name)
        if name:
            base = base.filter(name=name)
        for f in [BaseFilter.from_dict(x) for _, x in filters.items()]:
            base = f.contribute_to_query_set(base).filter(f)
        context.update(self._blocks_context(request, base, silk_request))
        return context

    def _blocks_context(self, request, qs, silk_request):
        """Code blocks and cProfile tabs. `qs` already carries the name, function and saved filters."""
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(func_name__icontains=q))
        tab = 'cprofile' if request.GET.get('tab') == 'cprofile' and not silk_request else 'blocks'
        sort = request.GET.get('sort', 'total')
        if sort not in profiling_data.BLOCK_SORTS:
            sort = 'total'
        requests_qs = Request.objects.all()
        ctx = {
            'q': q, 'tab': tab, 'sort': sort,
            'blocks': profiling_data.blocks(qs, sort),
            'cprofile_count': 0 if silk_request else requests_qs.exclude(pyprofile='').count(),
            'profile_count': qs.count(),
            'detail': None, 'cprofile': None,
        }
        block_id = request.GET.get('b', '')
        if tab == 'blocks' and block_id.isdigit():
            ctx['detail'] = profiling_data.block_detail(qs, int(block_id))
        if tab == 'cprofile':
            ctx['cprofile_requests'] = profiling_data.cprofile_requests(requests_qs)
            open_id = request.GET.get('c', '')
            opened = requests_qs.filter(pk=open_id).first() if _is_uuid(open_id) else None
            if opened:
                ctx['cprofile'] = {'request': opened,
                                   **profiling_data.parse_cprofile(opened.pyprofile, request.GET.get('cs', 'cumtime'))}
        return ctx

    def _render(self, request, context):
        template = 'silk/profiling.html'
        if request.headers.get('HX-Request'):
            template = 'silk/inclusion/profiling_split.html'
        return render(request, template, context)

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request, *args, **kwargs):
        return self._render(request, self._create_context(request, *args, **kwargs))

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def post(self, request):
        if 'clear_filters' in request.POST:
            filters_as_dict = {}
        else:
            filters = filters_from_request(request)
            filters_as_dict = {ident: f.as_dict() for ident, f in filters.items()}
        self.filters_manager.save(request, filters_as_dict)
        return self._render(request, self._create_context(request))
