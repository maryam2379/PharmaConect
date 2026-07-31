from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Order


@login_required
def order_list(request):
    orders = Order.objects.filter(user=request.user).select_related('pharmacy', 'wholesaler')
    return render(request, 'orders/order_list.html', {'orders': orders})


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'orders/order_detail.html', {'order': order})


@login_required
def order_create(request):
    if request.method == 'POST':
        order = Order.objects.create(
            user=request.user,
            pharmacy_id=request.POST.get('pharmacy_id'),
            wholesaler_id=request.POST.get('wholesaler_id'),
            reference=f"ORD-{request.user.id}-{Order.objects.count() + 1}",
            total_amount=request.POST.get('total_amount', 0),
        )
        return redirect('orders:order_detail', order_id=order.id)
    return render(request, 'orders/order_list.html')