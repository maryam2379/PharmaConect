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