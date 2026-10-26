"""Display formatting shared by templates and the text the views build."""


def ms_parts(ms):
    """(number, unit) for a duration: '273', 'ms' below a second, '5.09', 's' above."""
    ms = float(ms or 0)
    if abs(ms) >= 1000:
        s = ms / 1000
        return (f'{s:,.0f}' if abs(s) >= 10 else f'{s:.2f}'), 's'
    return (f'{ms:.1f}' if 0 < abs(ms) < 10 else f'{ms:.0f}'), 'ms'


def fmt_ms(ms):
    number, unit = ms_parts(ms)
    return f'{number} {unit}'


def fmt_int(n):
    """A count with thousands separators: 75973 as '75,973'. Anything else passes through."""
    try:
        return f'{int(n):,}'
    except (TypeError, ValueError):
        return n
