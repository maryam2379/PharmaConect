from django.urls import path
from . import views

app_name = 'pharmacies'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('stocks/', views.stock_list, name='stock_list'),
    path('stocks/create/', views.stock_create, name='stock_create'),
    path('stocks/<int:stock_id>/edit/', views.stock_update, name='stock_update'),
    path('stocks/<int:stock_id>/delete/', views.stock_delete, name='stock_delete'),
    path('<int:pharmacy_id>/', views.pharmacy_detail, name='pharmacy_detail'),
    path('nearby/', views.nearby_pharmacies, name='nearby'),

    # API
    path('api/stocks/', views.api_stock_list, name='api_stock_list'),
    path('api/stocks/<int:stock_id>/quantity/', views.api_adjust_quantity, name='api_adjust_quantity'),
]