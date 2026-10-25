from django.template import Library

register = Library()


def request_menu(request, silk_request):
    return {'request': request,
            'silk_request': silk_request}


def profile_menu(request, profile, silk_request=None):
    context = {'request': request, 'profile': profile}
    if silk_request:
        context['silk_request'] = silk_request
    return context


def code(lines, actual_line):
    # Exclude empty strings — otherwise every blank line in the snippet matches
    stripped_actual = {x.strip() for x in actual_line if x.strip()}
    active_indices = [i for i, line in enumerate(lines) if line.strip() and line.strip() in stripped_actual]
    return {'code': lines, 'actual_line': list(stripped_actual), 'active_indices': active_indices}


register.inclusion_tag('silk/inclusion/code.html')(code)
register.inclusion_tag('silk/inclusion/request_menu.html')(request_menu)
register.inclusion_tag('silk/inclusion/profile_menu.html')(profile_menu)
