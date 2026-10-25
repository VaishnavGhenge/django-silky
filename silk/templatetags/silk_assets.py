import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

import silk

register = template.Library()


@register.simple_tag
def silk_asset(path):
    """Static URL with a version stamp, so browsers never keep a stale copy.

    In DEBUG the stamp is the file's modification time, so edits show up on
    reload; otherwise it is the installed Silk version, which changes on upgrade.
    """
    stamp = silk.__version__
    if settings.DEBUG:
        found = finders.find(path)
        if found:
            stamp = str(int(os.path.getmtime(found)))
    return f'{static(path)}?v={stamp}'
