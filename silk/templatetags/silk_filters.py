import json
import os
import re

from django.template import Library
from django.template.defaultfilters import stringfilter
from django.utils import timezone
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = Library()


def _no_op(x):
    return x


def _esc_func(autoescape):
    if autoescape:
        return conditional_escape
    return _no_op


@stringfilter
def spacify(value, autoescape=None):
    esc = _esc_func(autoescape)
    val = esc(value).replace(' ', "&nbsp;")
    val = val.replace('\t', '    ')
    return mark_safe(val)


def _urlify(str):
    r = re.compile(r'"(?P<src>.*\.py)", line (?P<num>[0-9]+).*')
    m = r.search(str)
    while m:
        group = m.groupdict()
        src = group['src']
        num = group['num']
        start = m.start('src')
        end = m.end('src')
        rep = '<a href="/silk/src/?file_path={src}&line_num={num}">{src}</a>'.format(src=src, num=num)
        str = str[:start] + rep + str[end:]
        m = r.search(str)
    return str


@register.filter
def hash(h, key):
    return h[key]


def _process_microseconds(dt_strftime):
    splt = dt_strftime.split('.')
    micro = splt[-1]
    time = '.'.join(splt[0:-1])
    micro = '%.3f' % float('0.' + micro)
    return time + micro[1:]


def _silk_date_time(dt):
    today = timezone.now().date()
    if dt.date() == today:
        dt_strftime = dt.strftime('%H:%M:%S.%f')
        return _process_microseconds(dt_strftime)
    else:
        return _process_microseconds(dt.strftime('%Y.%m.%d %H:%M.%f'))


@register.filter(expects_localtime=True)
def silk_date_time(dt):
    return _silk_date_time(dt)


@register.filter(expects_localtime=True)
def silk_full_datetime(dt):
    """Full date + 12 h clock + optional timezone — used in hero bars."""
    if dt is None:
        return ''
    hour = dt.hour % 12 or 12
    am_pm = 'AM' if dt.hour < 12 else 'PM'
    date_part = '{} {}, {}'.format(dt.strftime('%b'), dt.day, dt.year)
    time_part = '{}:{} {}'.format(hour, dt.strftime('%M:%S'), am_pm)
    tz_name = dt.strftime('%Z')
    result = '{}, {}'.format(date_part, time_part)
    if tz_name and tz_name != 'UTC':
        result += ' {}'.format(tz_name)
    return result


@register.filter
def sorted(value):
    return sorted(value)


@register.filter
def unlocalize(value):
    """
    Render values without Django's locale-aware numeric formatting.
    """
    if value is None:
        return ''
    return str(value)


@stringfilter
def filepath_urlify(value, autoescape=None):
    value = _urlify(value)
    return mark_safe(value)


@stringfilter
def body_filter(value):
    print(value)
    if len(value) > 20:
        return 'Too big!'
    else:
        return value


@register.filter
@stringfilter
def app_path(value):
    """Show a source path relative to the project directory when it lives inside it."""
    root = os.getcwd().rstrip(os.sep) + os.sep
    return value[len(root):] if value.startswith(root) else value


@register.filter
@stringfilter
def path_dir(value):
    """Directory part of a path, with a trailing slash ('' when there is none)."""
    head, sep, _ = value.rpartition('/')
    return head + sep


@register.filter
@stringfilter
def path_name(value):
    """File name part of a path."""
    return value.rpartition('/')[2]


@register.filter
def silk_json(value):
    """Serialize a Python value to JSON, marked safe for template output."""
    return mark_safe(json.dumps(value))


spacify.needs_autoescape = True
filepath_urlify.needs_autoescape = True
register.filter(spacify)
register.filter(filepath_urlify)
register.filter(body_filter)


@register.simple_tag(takes_context=True)
def time_tier(context, ms):
    """'good', 'ok' or 'bad' for a duration, using the viewer's thresholds from Settings."""
    from silk.utils.prefs import thresholds, tier
    th = context.get('thresholds') or thresholds(context.get('request'))
    return tier(ms, th)


@register.filter(name='sql_type')
def sql_type_filter(sql):
    """SELECT, INSERT, UPDATE, DELETE or the query's first keyword."""
    from silk.utils.sql_patterns import sql_type
    return sql_type(sql or '')


@register.filter
def dur(ms):
    """A duration in ms as '273 ms' or '5.09 s'."""
    from silk.utils.fmt import fmt_ms
    return fmt_ms(ms)


@register.filter
def dur_num(ms):
    from silk.utils.fmt import ms_parts
    return ms_parts(ms)[0]


@register.filter
def dur_unit(ms):
    from silk.utils.fmt import ms_parts
    return ms_parts(ms)[1]


@register.filter
def num(n):
    """A count as '75,973'."""
    from silk.utils.fmt import fmt_int
    return fmt_int(n)
