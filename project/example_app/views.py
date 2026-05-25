import json
from time import sleep

from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView

from example_app import models
from silk.profiling.profiler import silk_profile


def index(request):
    @silk_profile()
    def do_something_long():
        sleep(1.345)

    with silk_profile(name='Why do this take so long?'):
        do_something_long()
    return render(request, 'example_app/index.html', {'blinds': models.Blind.objects.all()})


class ExampleCreateView(CreateView):
    model = models.Blind
    fields = ['name']
    success_url = reverse_lazy('example_app:index')


# ── JSON API views (used by silk_seed for realistic profiling data) ──────────

def api_blind_list(request):
    """GET /api/blinds/ — list with optional ?search= and ?child_safe= filters."""
    qs = models.Blind.objects.all()
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(name__icontains=search)
    child_safe = request.GET.get('child_safe', '')
    if child_safe in ('true', '1'):
        qs = qs.filter(child_safe=True)
    elif child_safe in ('false', '0'):
        qs = qs.filter(child_safe=False)
    data = [{'id': b.id, 'name': b.name, 'child_safe': b.child_safe} for b in qs]
    return JsonResponse({'results': data, 'count': len(data)})


@csrf_exempt
def api_blind_create(request):
    """POST /api/blinds/create — create a blind, return 201 JSON."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'invalid JSON'}, status=400)
    name = payload.get('name', '').strip()
    if not name:
        return JsonResponse({'error': 'name is required'}, status=400)
    blind = models.Blind.objects.create(name=name, child_safe=payload.get('child_safe', False))
    return JsonResponse({'id': blind.id, 'name': blind.name, 'child_safe': blind.child_safe}, status=201)


def api_blind_detail(request, pk):
    """GET /api/blinds/<pk>/ — single blind."""
    blind = get_object_or_404(models.Blind, pk=pk)
    return JsonResponse({'id': blind.id, 'name': blind.name, 'child_safe': blind.child_safe})


def api_blind_stats(request):
    """GET /api/blinds/stats/ — aggregate counts (intentional N+1 pattern for demo)."""
    total = models.Blind.objects.count()
    child_safe_count = models.Blind.objects.filter(child_safe=True).count()
    unsafe_count = models.Blind.objects.filter(child_safe=False).count()
    # Intentional per-row query to show N+1 in Silk
    names = []
    for blind in models.Blind.objects.all():
        names.append(models.Blind.objects.filter(pk=blind.pk).values_list('name', flat=True).first())
    return JsonResponse({
        'total': total,
        'child_safe': child_safe_count,
        'unsafe': unsafe_count,
        'names': names,
    })
