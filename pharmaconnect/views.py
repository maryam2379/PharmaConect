import os

from django.conf import settings
from django.http import HttpResponse


def service_worker(request):
    path = os.path.join(settings.BASE_DIR, 'static', 'js', 'sw.js')
    with open(path, 'r') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/javascript')


def manifest(request):
    path = os.path.join(settings.BASE_DIR, 'static', 'js', 'manifest.json')
    with open(path, 'r') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/json')