from django.db import models


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('confirmed', 'Confirmée'),
        ('delivered', 'Livrée'),
        ('cancelled', 'Annulée'),
    ]
    reference = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    pharmacy = models.ForeignKey('pharmacies.Pharmacy', on_delete=models.CASCADE, related_name='orders')
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='orders')
    wholesaler = models.ForeignKey('wholesalers.Wholesaler', on_delete=models.SET_NULL, null=True, related_name='orders')


class OrderItem(models.Model):
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    medicine = models.ForeignKey('anticounterfeit.Medicine', on_delete=models.CASCADE, related_name='order_items')