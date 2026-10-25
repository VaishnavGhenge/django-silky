from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag
def navactive(request, urls, *args, **kwargs):
    path = request.path
    urls = [reverse(url, args=args) for url in urls.split()]
    if path in urls:
        cls = kwargs.get('class', None)
        if not cls:
            cls = "menu-item-selected"
        return cls
    return ""


@register.simple_tag(takes_context=True)
def silky_nav_counts(context):
    """Counts for the sidebar items and quick views (cached briefly, see silk.utils.quick_views)."""
    from silk.utils.prefs import thresholds
    from silk.utils.quick_views import nav_counts
    request = context.get('request')
    if request is None:
        return {}
    return nav_counts(thresholds(request)['slow_ms'])
