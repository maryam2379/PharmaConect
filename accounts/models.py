from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = [
        ('patient', 'Patient'),
        ('pharmacien', 'Pharmacien'),
        ('grossiste', 'Grossiste'),
        ('admin', 'Admin'),
    ]
    phone = models.CharField(max_length=20)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_verified = models.BooleanField(default=False)
    verification_token = models.CharField(max_length=200, null=True, blank=True)
    otp_code = models.CharField(max_length=10, null=True, blank=True)
    documents = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    address = models.TextField(
        blank=True, null=True,
        help_text="Adresse complète (rue, quartier, ville, etc.)"
    )
    latitude = models.FloatField(
        blank=True, null=True,
        help_text="Latitude (coordonnées GPS)"
    )
    longitude = models.FloatField(
        blank=True, null=True,
        help_text="Longitude (coordonnées GPS)"
    )

    def __str__(self):
        return self.username