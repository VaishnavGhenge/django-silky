"""Sidebar counts and the quick views (Slow, Server errors, N+1, Slower than usual, Writes).

Counts are cached for a short while because the sidebar renders on every page.
"""
import statistics

from django.core.cache import cache

from silk.utils.insights import MIN_REQUESTS_FOR_USUAL, SLOWER_FACTOR, SLOWER_MIN_MS

CACHE_SECONDS = 30
SCAN_MAX = 20000     # newest requests read to find the slower-than-usual ones
WRITE_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']
QUICK_VIEWS = ['slow', 'errors', 'n1', 'slower', 'writes']


def slower_than_usual_ids():
    """Requests at least SLOWER_FACTOR times their endpoint's median, and SLOWER_MIN_MS over it."""
    from silk.models import Request
    rows = list(Request.objects.filter(time_taken__isnull=False).order_by('-start_time')
                .values_list('id', 'time_taken', 'view_name', 'path')[:SCAN_MAX])
    by = {}
    for r in rows:
        by.setdefault(r[2] or r[3], []).append(r)
    ids = []
    for group in by.values():
        if len(group) < MIN_REQUESTS_FOR_USUAL:
            continue
        median = statistics.median(r[1] for r in group)
        ids += [r[0] for r in group if r[1] >= median * SLOWER_FACTOR and r[1] - median >= SLOWER_MIN_MS]
    return ids


def nav_counts(slow_ms):
    """Counts for the sidebar items and quick views."""
    key = f'silky:nav:{slow_ms}'
    counts = cache.get(key)
    if counts is not None:
        return counts
    from silk.models import Profile, Request, SQLQuery
    from silk.utils.summary_data import repeating_request_ids
    counts = {
        'requests': Request.objects.count(),
        'sql': SQLQuery.objects.count(),
        'hotspots': SQLQuery.objects.exclude(code_location='').values('code_location').distinct().count(),
        'profiling': Profile.objects.count(),
        'slow': Request.objects.filter(time_taken__gte=slow_ms).count(),
        'errors': Request.objects.filter(response__status_code__gte=500).count(),
        'n1': len(repeating_request_ids()),
        'slower': len(slower_than_usual_ids()),
        'writes': Request.objects.filter(method__in=WRITE_METHODS).count(),
    }
    cache.set(key, counts, CACHE_SECONDS)
    return counts


def quick_filters(view, slow_ms):
    """Session filters (ident to dict) that a quick view stands for."""
    from silk.models import Response
    from silk.request_filters import (
        MultiMethodFilter, MultiStatusCodeFilter, NPlusOneFilter, OverallTimeFilter, SlowerThanUsualFilter,
    )
    if view == 'slow':
        return {'overalltime': OverallTimeFilter(slow_ms).as_dict()}
    if view == 'errors':
        codes = sorted(set(Response.objects.filter(status_code__gte=500).values_list('status_code', flat=True))) or [500]
        return {'status_code': MultiStatusCodeFilter(codes).as_dict()}
    if view == 'n1':
        return {'nplusone': NPlusOneFilter('1').as_dict()}
    if view == 'slower':
        return {'slower': SlowerThanUsualFilter('1').as_dict()}
    if view == 'writes':
        return {'method': MultiMethodFilter(WRITE_METHODS).as_dict()}
    return {}
