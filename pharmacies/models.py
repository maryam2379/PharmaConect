from django.db import models
from django.conf import settings


class Pharmacy(models.Model):
    PLAN_CHOICES = [
        ('basic', 'Basic'),
        ('premium', 'Premium'),
    ]
    name = models.CharField(max_length=150)
    license_number = models.CharField(max_length=50, unique=True)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=50)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    subscription_plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='basic')
    subscription_end = models.DateTimeField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    manager = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='pharmacy'
    )

    def __str__(self):
        return self.name


class Stock(models.Model):
    quantity = models.PositiveIntegerField(default=0)
    batch_number = models.CharField(max_length=200, null=True, blank=True)
    expiry_date = models.DateField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    last_updated = models.DateTimeField(auto_now=True)

    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name='stocks')
    medicine = models.ForeignKey('anticounterfeit.Medicine', on_delete=models.CASCADE, related_name='stocks')

    class Meta:
        indexes = [models.Index(fields=['expiry_date'])]


class OfflineSync(models.Model):
    pending_updates = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True, blank=True)

    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name='offline_syncs')