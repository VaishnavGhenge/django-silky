from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk.auth import login_possibly_required, permissions_possibly_required
from silk.models import Request
from silk.utils import compare

FIELD_FORMAT = '%Y-%m-%dT%H:%M'   # what <input type="datetime-local"> sends


def _parse(value):
    dt = parse_datetime(value or '')
    if dt is None:
        return None
    if settings.USE_TZ and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _field(dt):
    return compare.local(dt).strftime(FIELD_FORMAT)


def _range_link(a, b, ep=''):
    from urllib.parse import urlencode
    params = {'a0': _field(a[0]), 'a1': _field(a[1]), 'b0': _field(b[0]), 'b1': _field(b[1])}
    if ep:
        params['ep'] = ep
    return '?' + urlencode(params)


class CompareRangesView(View):
    """Two time ranges, for example before and after a deploy."""

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request):
        presets = compare.presets()
        ep = request.GET.get('ep', '')
        bounds = [_parse(request.GET.get(k)) for k in ('a0', 'a1', 'b0', 'b1')]
        error = None
        if all(bounds) and (bounds[0] >= bounds[1] or bounds[2] >= bounds[3]):
            error = '“From” must be before “To” in both ranges.'
        if not all(bounds) or error:
            preset = compare.default_ranges(presets)
            if not preset:
                return render(request, 'silk/compare_range.html', {'request': request, 'empty': True, 'mode': 'range'})
            bounds = [*preset['a'], *preset['b']]
        a, b = (bounds[0], bounds[1]), (bounds[2], bounds[3])
        active = next((p for p in presets if p['a'] == a and p['b'] == b), None)
        for p in presets:
            p['link'] = _range_link(p['a'], p['b'], ep)
        data = compare.compare_ranges(a, b, ep)
        for item in data['menu']:
            item['link'] = _range_link(a, b, item['key'])
        for e in data['endpoints']:
            e['link'] = _range_link(a, b, e['key'])
        context = {
            'request': request, 'mode': 'range', 'ep': ep, 'error': error,
            'a': a, 'b': b, 'fields': {k: _field(v) for k, v in zip(('a0', 'a1', 'b0', 'b1'), bounds)},
            'presets': presets, 'active_preset': active,
            'swap_link': _range_link(b, a, ep), 'all_link': _range_link(a, b),
            'tz': timezone.get_current_timezone_name() if settings.USE_TZ else '',
            **data,
        }
        return render(request, 'silk/compare_range.html', context)


class ComparePickView(View):
    """Endpoints with history, to pick a pair of requests."""

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request):
        q = request.GET.get('q', '').strip()
        context = {'request': request, 'mode': 'requests', 'q': q, 'endpoints': compare.endpoints_with_history(q)}
        template = 'silk/compare_pick.html'
        if request.headers.get('HX-Request'):
            template = 'silk/inclusion/compare_pick_rows.html'
        return render(request, template, context)


class CompareRequestsView(View):
    """Two requests to the same endpoint (or any two requests) side by side."""

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request, a_id, b_id):
        a = get_object_or_404(Request, pk=a_id)
        b = get_object_or_404(Request, pk=b_id)
        context = {'request': request, 'mode': 'requests', 'only_changes': request.GET.get('all') != '1',
                   **compare.compare_requests(a, b)}
        return render(request, 'silk/compare_requests.html', context)
