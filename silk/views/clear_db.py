import os
import shutil

from django.db import transaction
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk.auth import login_possibly_required, permissions_possibly_required
from silk.config import SilkyConfig
from silk.models import Profile, Request, Response, SQLQuery
from silk.utils.data_deletion import delete_model


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

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request, *_, **kwargs):
        return render(request, 'silk/clear_db.html', context=_retention_context())

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def post(self, request, *_, **kwargs):
        context = _retention_context()
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

        if cleared:
            context['msg'] = 'Cleared data for: {}'.format(', '.join(cleared))

        return render(request, 'silk/clear_db.html', context=context)
