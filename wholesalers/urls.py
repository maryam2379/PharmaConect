from django.urls import path
from . import views

app_name = 'wholesalers'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('offers/', views.offer_list, name='offer_list'),
    path('offers/create/', views.offer_create, name='offer_create'),
    path('offers/<int:offer_id>/edit/', views.offer_update, name='offer_update'),
    path('offers/<int:offer_id>/delete/', views.offer_delete, name='offer_delete'),
]