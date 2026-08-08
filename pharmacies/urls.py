from django.urls import path
from . import views

app_name = 'pharmacies'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('my-pharmacy/', views.my_pharmacy, name='my_pharmacy'),
    path('stocks/', views.stock_list, name='stock_list'),
    path('stocks/create/', views.stock_create, name='stock_create'),
    path('stocks/<int:stock_id>/edit/', views.stock_update, name='stock_update'),
    path('stocks/<int:stock_id>/delete/', views.stock_delete, name='stock_delete'),
    path('<int:pharmacy_id>/', views.pharmacy_detail, name='pharmacy_detail'),
    path('nearby/', views.nearby_pharmacies, name='nearby'),
    path('scan_pharmacies/', views.scan, name='scan'),
    path('api/scan/', views.api_scan, name='api_scan'),
    path('api/scan/upload/', views.api_upload_qrcode, name='api_upload_qrcode'),

    # API
    path('api/stocks/', views.api_stock_list, name='api_stock_list'),
    path('api/stocks/<int:stock_id>/quantity/', views.api_adjust_quantity, name='api_adjust_quantity'),
]