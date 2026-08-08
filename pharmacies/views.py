import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import Pharmacy, Stock
from anticounterfeit.models import Medicine, QRCode, ScanLog
import re
from datetime import datetime
from io import BytesIO
from PIL import Image
from pyzbar.pyzbar import decode as decode_barcode

@login_required
def dashboard(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)
    stocks = pharmacy.stocks.select_related('medicine')
    return render(request, 'admin/pharmacies/dashboard.html', {'pharmacy': pharmacy, 'stocks': stocks})


@login_required
def scan(request):
    return render(request, 'admin/pharmacies/scan.html')


@login_required
def stock_list(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)
    stocks = pharmacy.stocks.select_related('medicine')
    return render(request, 'admin/pharmacies/stocks.html', {'stocks': stocks, 'pharmacy': pharmacy})


@login_required
def stock_create(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)
    if request.method == 'POST':
        Stock.objects.create(
            pharmacy=pharmacy,
            medicine_id=request.POST.get('medicine_id'),
            quantity=request.POST.get('quantity'),
            price=request.POST.get('price'),
            expiry_date=request.POST.get('expiry_date'),
            batch_number=request.POST.get('batch_number'),
        )
        return redirect('pharmacies:stock_list')
    return render(request, 'pharmacies/stock_form.html')


@login_required
def stock_update(request, stock_id):
    stock = get_object_or_404(Stock, id=stock_id, pharmacy__manager=request.user)
    if request.method == 'POST':
        stock.quantity = request.POST.get('quantity', stock.quantity)
        stock.price = request.POST.get('price', stock.price)
        stock.save()
        return redirect('pharmacies:stock_list')
    return render(request, 'pharmacies/stock_form.html', {'stock': stock})


@login_required
def stock_delete(request, stock_id):
    stock = get_object_or_404(Stock, id=stock_id, pharmacy__manager=request.user)
    stock.delete()
    return redirect('pharmacies:stock_list')


def pharmacy_detail(request, pharmacy_id):
    pharmacy = get_object_or_404(Pharmacy, id=pharmacy_id)
    return render(request, 'pharmacies/pharmacy_detail.html', {'pharmacy': pharmacy})


def nearby_pharmacies(request):
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    pharmacies = Pharmacy.objects.filter(is_verified=True)
    return render(request, 'pharmacies.html', {'pharmacies': pharmacies})


# ── API ──
@login_required
@require_http_methods(["GET"])
def api_stock_list(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)
    data = list(pharmacy.stocks.values('id', 'medicine__name', 'quantity', 'price', 'expiry_date'))
    return JsonResponse({'stocks': data})


@login_required
@require_http_methods(["PATCH"])
def api_adjust_quantity(request, stock_id):
    stock = get_object_or_404(Stock, id=stock_id, pharmacy__manager=request.user)
    body = json.loads(request.body)
    stock.quantity = body.get('quantity', stock.quantity)
    stock.save(update_fields=['quantity'])
    return JsonResponse({'success': True, 'quantity': stock.quantity})


@login_required
@require_http_methods(["POST"])
def api_scan_add_stock(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Code invalide'}, status=400)

    medicine_id = data.get('medicine_id')
    if not medicine_id:
        return JsonResponse({'success': False, 'error': 'Médicament non reconnu'}, status=400)

    medicine = get_object_or_404(Medicine, id=medicine_id)

    batch_number = data.get('batch_number') or ''
    expiry_date = data.get('expiry_date') or None
    price = data.get('price') or None

    try:
        quantity = int(data.get('quantity') or 1)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Quantité invalide'}, status=400)

    stock, created = Stock.objects.get_or_create(
        pharmacy=pharmacy,
        medicine=medicine,
        batch_number=batch_number,
        defaults={'quantity': quantity, 'price': price, 'expiry_date': expiry_date}
    )
    if not created:
        stock.quantity += quantity
        stock.save(update_fields=['quantity'])

    return JsonResponse({
        'success': True,
        'created': created,
        'medicine_name': medicine.name,
        'quantity': stock.quantity,
    })

def parse_code(code):
    """Détecte le format du code et en extrait gtin/lot/expiration/série."""
    code = code.strip()

    # JSON structuré
    if code.startswith('{'):
        try:
            data = json.loads(code)
            return {'source': 'json', **data}
        except json.JSONDecodeError:
            pass

    # Format interne PHARMA-CM-XXXXXX|LOT|EXP
    if '|' in code:
        parts = code.split('|')
        return {
            'source': 'pipe',
            'serial_number': parts[0] if len(parts) > 0 else '',
            'batch_number': parts[1] if len(parts) > 1 else '',
            'expiry_date': parts[2] if len(parts) > 2 else '',
        }

    # GS1 (DataMatrix) : (01)GTIN(17)EXP(10)LOT(21)SERIAL
    if code.startswith('01') and len(code) >= 16:
        result = {'source': 'gs1'}
        m = re.search(r'01(\d{14})', code)
        if m:
            result['gtin'] = m.group(1)
        m = re.search(r'17(\d{6})', code)
        if m:
            try:
                result['expiry_date'] = datetime.strptime(m.group(1), '%y%m%d').date().isoformat()
            except ValueError:
                pass
        m = re.search(r'10([^\x1d]+?)(?:\x1d|21|$)', code)
        if m:
            result['batch_number'] = m.group(1)
        m = re.search(r'21([^\x1d]+)$', code)
        if m:
            result['serial_number'] = m.group(1)
        return result

    # GTIN/EAN pur (8, 12, 13 ou 14 chiffres)
    if code.isdigit() and len(code) in (8, 12, 13, 14):
        return {'source': 'gtin', 'gtin': code}

    return {'source': 'raw', 'serial_number': code}


@login_required
@require_http_methods(["POST"])
def api_scan(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Requête invalide'}, status=400)

    raw_code = (body.get('code') or '').strip()
    if not raw_code:
        return JsonResponse({'success': False, 'message': 'Code vide'}, status=400)

    parsed = parse_code(raw_code)

    # Authenticité : un code déjà scanné = suspect (potentiel réemballage/contrefaçon)
    scan_log, is_first_scan = ScanLog.objects.get_or_create(
        code=raw_code,
        defaults={'scanned_by': request.user}
    )
    authentic = is_first_scan

    # Résolution du médicament
    medicine = None
    is_new_medicine = False
    if parsed.get('medicine_id'):
        medicine = Medicine.objects.filter(id=parsed['medicine_id']).first()
    if not medicine and parsed.get('gtin'):
        medicine = Medicine.objects.filter(gtin=parsed['gtin']).first()
    if not medicine and parsed.get('medicine_name'):
        medicine, is_new_medicine = Medicine.objects.get_or_create(
            name=parsed['medicine_name'],
            defaults={
                'gtin': parsed.get('gtin', ''),
                'generic_name': parsed.get('generic_name', ''),
                'manufacturer': parsed.get('manufacturer', ''),
                'dosage': parsed.get('dosage', ''),
                'form': parsed.get('form', ''),
            }
        )

    if not medicine:
        return JsonResponse({
            'success': False,
            'not_found': True,
            'message': "Médicament non reconnu — ce code n'existe pas en base."
        })

    # Auto-insertion au stock de la pharmacie connectée
    auto_inserted = False
    pharmacy = Pharmacy.objects.filter(manager=request.user).first()
    if pharmacy:
        stock, created = Stock.objects.get_or_create(
            pharmacy=pharmacy,
            medicine=medicine,
            batch_number=parsed.get('batch_number', ''),
            defaults={
                'quantity': 1,
                'expiry_date': parsed.get('expiry_date') or None,
            }
        )
        if not created:
            stock.quantity += 1
            stock.save(update_fields=['quantity'])
        auto_inserted = True

    scan_log.medicine = medicine
    scan_log.batch_number = parsed.get('batch_number', '')
    scan_log.save(update_fields=['medicine', 'batch_number'])

    return JsonResponse({
        'success': True,
        'auto_inserted': auto_inserted,
        'is_new_medicine': is_new_medicine,
        'already_known': not is_new_medicine and not auto_inserted,
        'source': parsed.get('source'),
        'medicine': {
            'name': medicine.name,
            'generic_name': getattr(medicine, 'generic_name', ''),
            'manufacturer': getattr(medicine, 'manufacturer', ''),
            'dosage': getattr(medicine, 'dosage', ''),
            'form': getattr(medicine, 'form', ''),
            'gtin': getattr(medicine, 'gtin', ''),
            'prescription_required': getattr(medicine, 'prescription_required', False),
            'authentic': authentic,
            'batch_number': parsed.get('batch_number', ''),
            'expiry_date': parsed.get('expiry_date', ''),
        }
    })


@login_required
@require_http_methods(["POST"])
def api_upload_qrcode(request):
    image_file = request.FILES.get('image')
    if not image_file:
        return JsonResponse({'success': False, 'message': 'Aucune image reçue'}, status=400)

    try:
        image = Image.open(BytesIO(image_file.read()))
        results = decode_barcode(image)
    except Exception:
        return JsonResponse({'success': False, 'message': "Impossible de lire l'image"}, status=400)

    if not results:
        return JsonResponse({'success': False, 'message': 'Aucun QR code ou code-barres détecté'})

    code = results[0].data.decode('utf-8')
    return JsonResponse({'success': True, 'code': code})

EDITABLE_PHARMACY_FIELDS = ['name', 'address', 'city', 'phone', 'email', 'latitude', 'longitude']


EDITABLE_PHARMACY_FIELDS = ['name', 'address', 'city', 'phone', 'email', 'latitude', 'longitude', 'logo']


@login_required
def my_pharmacy(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)

    if request.method == 'POST':
        errors = {}

        name = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()
        city = request.POST.get('city', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()
        latitude = request.POST.get('latitude', '').strip()
        longitude = request.POST.get('longitude', '').strip()
        remove_logo = request.POST.get('remove_logo') == '1'
        logo_file = request.FILES.get('logo')

        if not name:
            errors['name'] = "Le nom est requis."
        if not address:
            errors['address'] = "L'adresse est requise."
        if not city:
            errors['city'] = "La ville est requise."
        if not phone:
            errors['phone'] = "Le téléphone est requis."
        if not email:
            errors['email'] = "L'email est requis."

        if logo_file:
            if not logo_file.content_type.startswith('image/'):
                errors['logo'] = "Le fichier doit être une image."
            elif logo_file.size > 2 * 1024 * 1024:
                errors['logo'] = "L'image ne doit pas dépasser 2 Mo."

        if latitude:
            try:
                latitude = float(latitude)
            except ValueError:
                errors['latitude'] = "Latitude invalide."
        else:
            latitude = None

        if longitude:
            try:
                longitude = float(longitude)
            except ValueError:
                errors['longitude'] = "Longitude invalide."
        else:
            longitude = None

        if errors:
            return render(request, 'admin/pharmacies/my_pharmacy.html', {
                'pharmacy': pharmacy,
                'errors': errors,
                'posted': request.POST,
            })

        pharmacy.name = name
        pharmacy.address = address
        pharmacy.city = city
        pharmacy.phone = phone
        pharmacy.email = email
        pharmacy.latitude = latitude
        pharmacy.longitude = longitude

        if remove_logo and not logo_file:
            pharmacy.logo.delete(save=False)
            pharmacy.logo = None
        elif logo_file:
            pharmacy.logo = logo_file

        pharmacy.save(update_fields=EDITABLE_PHARMACY_FIELDS)

        return redirect('pharmacies:my_pharmacy')

    return render(request, 'admin/pharmacies/my_pharmacy.html', {'pharmacy': pharmacy})