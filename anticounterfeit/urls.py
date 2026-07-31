from django.urls import path
from . import views

app_name = 'anticounterfeit'

urlpatterns = [
    path('scan/', views.scan_page, name='scan_page'),
    path('api/scan/', views.api_scan, name='api_scan'),
    path('api/upload-qrcode/', views.api_upload_qrcode, name='api_upload_qrcode'),
]