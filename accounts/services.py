import secrets
from django.core.mail import send_mail
from django.conf import settings


def generate_otp():
    return str(secrets.randbelow(900000) + 100000)


def send_otp_email(user):
    send_mail(
        subject="Votre code de vérification PharmaConnect",
        message=f"Votre code OTP : {user.otp_code}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def send_verification_email(user, verification_url):
    send_mail(
        subject="Vérifiez votre compte PharmaConnect",
        message=f"Cliquez ici pour vérifier votre compte : {verification_url}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )