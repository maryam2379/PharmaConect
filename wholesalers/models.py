from django.db import models
from django.conf import settings


class Wholesaler(models.Model):
    name = models.CharField(max_length=150)
    license_number = models.CharField(max_length=50, unique=True)
    contact = models.CharField(max_length=20)
    email = models.EmailField()
    address = models.CharField(max_length=200)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    manager = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='wholesaler'
    )

    def __str__(self):
        return self.name


class SupplyOffer(models.Model):
    """Offre de vente en gros faite par un grossiste vers les pharmacies"""
    wholesaler = models.ForeignKey(Wholesaler, on_delete=models.CASCADE, related_name='offers')
    medicine = models.ForeignKey('anticounterfeit.Medicine', on_delete=models.CASCADE, related_name='supply_offers')
    quantity_available = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    min_order_quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)