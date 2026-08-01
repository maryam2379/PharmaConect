from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('search/', views.search_medicine, name='search'),
    path('history/', views.search_history, name='history'),
]