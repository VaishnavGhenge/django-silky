"""Per-browser preferences that change what the server renders.

The Settings page stores thresholds in cookies so views can colour rows and
filter slow requests with the viewer's numbers. Everything else (theme, editor,
charts) lives in localStorage and never reaches the server.
"""
SLOW_MS = 1000   # red, and the Slow filter
OK_MS = 300      # amber from here up to SLOW_MS

_LIMITS = {'silky-slow-ms': (SLOW_MS, 50, 600000), 'silky-ok-ms': (OK_MS, 10, 600000)}


def _cookie_int(request, name):
    default, lo, hi = _LIMITS[name]
    cookies = getattr(request, 'COOKIES', None) or {}
    try:
        value = int(cookies.get(name, default))
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, value))


def thresholds(request):
    slow = _cookie_int(request, 'silky-slow-ms')
    ok = min(_cookie_int(request, 'silky-ok-ms'), slow - 1)
    return {'slow_ms': slow, 'ok_ms': ok}


def tier(ms, th):
    ms = ms or 0
    return 'good' if ms < th['ok_ms'] else 'ok' if ms < th['slow_ms'] else 'bad'
