import os
import shutil

from django.db import transaction
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk.auth import login_possibly_required, permissions_possibly_required
from silk.config import SilkyConfig
from silk.models import Profile, Request, Response, SQLQuery
from silk.utils import prefs
from silk.utils.data_deletion import delete_model
from silk.utils.insights import app_frame

# Settings shown under Recording, with a risk note for values that expose data or let it grow unbounded.
RECORDING_KEYS = [
    'SILKY_AUTHENTICATION', 'SILKY_AUTHORISATION', 'SILKY_PYTHON_PROFILER', 'SILKY_PYTHON_PROFILER_BINARY',
    'SILKY_META', 'SILKY_INTERCEPT_PERCENT', 'SILKY_INTERCEPT_STATUS_CODES', 'SILKY_GARBAGE_COLLECT_MODE',
    'SILKY_MAX_RECORDED_REQUESTS', 'SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT', 'SILKY_MAX_RECORDED_TIME',
    'SILKY_MAX_REQUEST_BODY_SIZE', 'SILKY_MAX_RESPONSE_BODY_SIZE', 'SILKY_HIDE_COOKIES', 'SILKY_ANALYZE_QUERIES',
    'SILKY_DELETE_PROFILES',
]
# Read with a falsy fallback where SilkyConfig.defaults has no entry.
IMPLICIT_DEFAULTS = {'SILKY_PYTHON_PROFILER_BINARY': False}
RECOMMENDED = {
    'SILKY_AUTHENTICATION': True,
    'SILKY_AUTHORISATION': True,
    'SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT': 10,
    'SILKY_HIDE_COOKIES': True,
    'SILKY_ANALYZE_QUERIES': False,
}


def _risk(key, config):
    value = getattr(config, key)
    if key == 'SILKY_AUTHENTICATION' and not value:
        return 'Anyone who can reach this URL can open Silk without logging in.'
    if key == 'SILKY_AUTHORISATION' and not value and config.SILKY_AUTHENTICATION:
        return 'Any logged-in user can see every recorded request, not only staff.'
    if (key == 'SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT' and not value
            and config.SILKY_GARBAGE_COLLECT_MODE in ('count', 'both')):
        return 'Count-based garbage collection never runs, so recorded data grows until you run silk_request_garbage_collect.'
    if key == 'SILKY_HIDE_COOKIES' and not value:
        return 'Cookies, including session ids, are stored in plain text with each request.'
    if key == 'SILKY_ANALYZE_QUERIES' and value:
        return 'Every query is run a second time under EXPLAIN ANALYZE, including INSERT, UPDATE and DELETE.'
    return ''


def _recording_context():
    config = SilkyConfig()
    rows = []
    for key in RECORDING_KEYS:
        value, default = getattr(config, key), SilkyConfig.defaults.get(key, IMPLICIT_DEFAULTS.get(key))
        rows.append({'key': key, 'value': repr(value), 'default': repr(default),
                     'changed': value != default, 'risk': _risk(key, config)})
    risks = [r for r in rows if r['risk']]
    fix = ''.join(f'{r["key"]} = {RECOMMENDED[r["key"]]!r}\n' for r in risks if r['key'] in RECOMMENDED)
    return {'recording': rows, 'risks': risks, 'recommended': fix}


def _data_context():
    oldest = Request.objects.order_by('start_time').values_list('start_time', flat=True).first()
    tb = SQLQuery.objects.exclude(code_location='').values_list('traceback', flat=True).first()
    return {'data': {'requests': Request.objects.count(), 'queries': SQLQuery.objects.count(),
                     'profiles': Profile.objects.count(), 'oldest': oldest},
            'sample_frame': app_frame(tb) if tb else None}


def _retention_context():
    """Read-only snapshot of the active garbage-collection policy for display."""
    config = SilkyConfig()
    mode = config.SILKY_GARBAGE_COLLECT_MODE
    return {
        'retention': {
            'mode': mode,
            'shows_count': mode in ('count', 'both'),
            'shows_time': mode in ('time', 'both'),
            'max_requests': config.SILKY_MAX_RECORDED_REQUESTS,
            'max_time': config.SILKY_MAX_RECORDED_TIME,
            'max_time_label': _humanize_minutes(config.SILKY_MAX_RECORDED_TIME),
        }
    }


def _humanize_minutes(minutes):
    if not minutes:
        return None
    units = (('day', 60 * 24), ('hour', 60), ('minute', 1))
    parts = []
    remaining = int(minutes)
    for name, size in units:
        if remaining >= size:
            value, remaining = divmod(remaining, size)
            parts.append(f"{value} {name}{'s' if value != 1 else ''}")
    return ', '.join(parts)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ClearDBView(View):

    def _context(self, request, **extra):
        return {**_retention_context(), **_recording_context(), **_data_context(),
                'thresholds': prefs.thresholds(request), 'defaults': {'slow_ms': prefs.SLOW_MS, 'ok_ms': prefs.OK_MS, 'n1_min': prefs.N1_MIN},
                **extra}

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request, *_, **kwargs):
        return render(request, 'silk/clear_db.html', context=self._context(request))

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def post(self, request, *_, **kwargs):
        if 'run_gc' in request.POST:
            before = Request.objects.count()
            Request.garbage_collect(force=True)
            removed = before - Request.objects.count()
            msg = f'Garbage collection removed {removed} request{"s" if removed != 1 else ""}.'
            return render(request, 'silk/clear_db.html', context=self._context(request, msg=msg))
        cleared = []

        if 'clear_all' in request.POST:
            delete_model(Profile)
            delete_model(SQLQuery)
            delete_model(Response)
            delete_model(Request)
            cleared = ['Response', 'SQLQuery', 'Profile', 'Request']

            if SilkyConfig().SILKY_DELETE_PROFILES:
                dir = SilkyConfig().SILKY_PYTHON_PROFILER_RESULT_PATH
                for files in os.listdir(dir):
                    path = os.path.join(dir, files)
                    try:
                        shutil.rmtree(path)
                    except OSError:
                        os.remove(path)
                cleared.append('profiler files')
        else:
            if 'clear_requests' in request.POST:
                delete_model(SQLQuery)
                delete_model(Response)
                delete_model(Request)
                cleared += ['Response', 'SQLQuery', 'Request']
            if 'clear_profiling' in request.POST:
                delete_model(Profile)
                cleared.append('Profile')

                if SilkyConfig().SILKY_DELETE_PROFILES:
                    dir = SilkyConfig().SILKY_PYTHON_PROFILER_RESULT_PATH
                    for files in os.listdir(dir):
                        path = os.path.join(dir, files)
                        try:
                            shutil.rmtree(path)
                        except OSError:
                            os.remove(path)
                    cleared.append('profiler files')

        msg = 'Cleared data for: {}'.format(', '.join(cleared)) if cleared else None
        return render(request, 'silk/clear_db.html', context=self._context(request, msg=msg))
