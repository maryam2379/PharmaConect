from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import PatientSearchHistory
from anticounterfeit.models import Medicine
from pharmacies.models import Stock

@login_required
def search_medicine(request):
    query = request.GET.get('q', '')
    results = []
    if query:
        results = Stock.objects.filter(medicine__name__icontains=query, quantity__gt=0).select_related('pharmacy', 'medicine')
        PatientSearchHistory.objects.create(patient=request.user, medicine_name=query)
    return render(request, 'patients/search.html', {'results': results, 'query': query})


@login_required
def search_history(request):
    history = PatientSearchHistory.objects.filter(patient=request.user).order_by('-searched_at')
    return render(request, 'patients/search_history.html', {'history': history})

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import PatientSearchHistory
from anticounterfeit.models import ScanLog
from orders.models import Order


def home(request):
    return render(request, "patients/index.html")


@login_required
def dashboard(request):
    search_history = PatientSearchHistory.objects.filter(patient=request.user).order_by('-searched_at')
    scan_count = ScanLog.objects.filter(scanned_by=request.user).count()
    pending_orders_count = Order.objects.filter(user=request.user, status='pending').count()

    return render(request, 'admin/patients/dashboard.html', {
        'search_count': search_history.count(),
        'recent_searches': search_history[:5],
        'scan_count': scan_count,
        'pending_orders_count': pending_orders_count,
    })


@login_required
def search_medicine(request):
    from pharmacies.models import Stock

    query = request.GET.get('q', '')
    results = []
    if query:
        results = Stock.objects.filter(medicine__name__icontains=query, quantity__gt=0).select_related('pharmacy', 'medicine')
        PatientSearchHistory.objects.create(patient=request.user, medicine_name=query)
    return render(request, 'patients/search.html', {'results': results, 'query': query})


@login_required
def search_history(request):
    history = PatientSearchHistory.objects.filter(patient=request.user).order_by('-searched_at')
    return render(request, 'patients/search_history.html', {'history': history})