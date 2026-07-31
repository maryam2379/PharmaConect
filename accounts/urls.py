from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('upload-document/', views.upload_document, name='upload_document'),
    path('verification-choice/', views.verification_choice, name='verification_choice'),
    path('send-otp/', views.send_otp_route, name='send_otp'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('send-verification-link/', views.send_verification_link, name='send_verification_link'),
    path('verify-email/<str:token>/', views.verify_email, name='verify_email'),

    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
]