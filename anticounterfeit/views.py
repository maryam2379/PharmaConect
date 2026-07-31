from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from .services import decode_medicine_from_code
from .models import ScanLog, QRCode


def scan_page(request):
    return render(request, 'anticounterfeit/scan.html')


@login_required
@require_http_methods(["POST"])
def api_scan(request):
    raw_code = request.POST.get('code')
    if not raw_code:
        return JsonResponse({'error': 'Code requis'}, status=400)

    result = decode_medicine_from_code(raw_code)

    ScanLog.objects.create(
        raw_code=raw_code,
        result=result['status'] if result['status'] in ('authentic', 'counterfeit') else 'unknown',
        scanned_by=request.user,
    )

    return JsonResponse({
        'status': result['status'],
        'medicine': result['medicine'].name if result.get('medicine') else None,
        'pharmacy': result['pharmacy'].name if result.get('pharmacy') else None,
    })


@login_required
@require_http_methods(["POST"])
def api_upload_qrcode(request):
    image = request.FILES.get('qrcode_image')
    if not image:
        return JsonResponse({'error': 'Image requise'}, status=400)
    # décodage image → code (pyzbar / qreader), puis réutiliser decode_medicine_from_code
    return JsonResponse({'success': True})