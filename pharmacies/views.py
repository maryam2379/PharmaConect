from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import Pharmacy, Stock


@login_required
def dashboard(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)
    stocks = pharmacy.stocks.select_related('medicine')
    return render(request, 'admin/pharmacies/dashboard.html', {'pharmacy': pharmacy, 'stocks': stocks})


@login_required
def stock_list(request):
    pharmacy = get_object_or_404(Pharmacy, manager=request.user)
    stocks = pharmacy.stocks.select_related('medicine')
    return render(request, 'admin/pharmacies/stocks.html', {'stocks': stocks})


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
    import json
    stock = get_object_or_404(Stock, id=stock_id, pharmacy__manager=request.user)
    body = json.loads(request.body)
    stock.quantity = body.get('quantity', stock.quantity)
    stock.save(update_fields=['quantity'])
    return JsonResponse({'success': True, 'quantity': stock.quantity})