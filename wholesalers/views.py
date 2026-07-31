from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Wholesaler, SupplyOffer


@login_required
def dashboard(request):
    wholesaler = get_object_or_404(Wholesaler, manager=request.user)
    offers = wholesaler.offers.select_related('medicine')
    return render(request, 'wholesalers/dashboard.html', {'wholesaler': wholesaler, 'offers': offers})


@login_required
def offer_list(request):
    wholesaler = get_object_or_404(Wholesaler, manager=request.user)
    offers = wholesaler.offers.select_related('medicine')
    return render(request, 'wholesalers/offer_list.html', {'offers': offers})


@login_required
def offer_create(request):
    wholesaler = get_object_or_404(Wholesaler, manager=request.user)
    if request.method == 'POST':
        SupplyOffer.objects.create(
            wholesaler=wholesaler,
            medicine_id=request.POST.get('medicine_id'),
            quantity_available=request.POST.get('quantity_available'),
            unit_price=request.POST.get('unit_price'),
            min_order_quantity=request.POST.get('min_order_quantity', 1),
        )
        return redirect('wholesalers:offer_list')
    return render(request, 'wholesalers/offer_form.html')


@login_required
def offer_update(request, offer_id):
    offer = get_object_or_404(SupplyOffer, id=offer_id, wholesaler__manager=request.user)
    if request.method == 'POST':
        offer.quantity_available = request.POST.get('quantity_available', offer.quantity_available)
        offer.unit_price = request.POST.get('unit_price', offer.unit_price)
        offer.save()
        return redirect('wholesalers:offer_list')
    return render(request, 'wholesalers/offer_form.html', {'offer': offer})


@login_required
def offer_delete(request, offer_id):
    offer = get_object_or_404(SupplyOffer, id=offer_id, wholesaler__manager=request.user)
    offer.delete()
    return redirect('wholesalers:offer_list')