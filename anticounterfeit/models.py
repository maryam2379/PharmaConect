from django.db import models


class Medicine(models.Model):
    name = models.CharField(max_length=150)
    generic_name = models.CharField(max_length=150, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    dosage = models.CharField(max_length=50, blank=True)
    form = models.CharField(max_length=50, blank=True)
    prescription_required = models.BooleanField(default=False)
    image_url = models.URLField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class QRCode(models.Model):
    STATUS_CHOICES = [
        ('active', 'Actif'),
        ('flagged', 'Suspect'),
        ('revoked', 'Révoqué'),
    ]
    code = models.TextField(unique=True)
    serial_number = models.TextField(unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.CharField(max_length=20, blank=True)

    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='qr_codes')
    pharmacy = models.ForeignKey('pharmacies.Pharmacy', on_delete=models.SET_NULL, null=True, blank=True, related_name='qrcodes')


class ScanLog(models.Model):
    """Historique des scans de vérification (détection de contrefaçon)"""
    RESULT_CHOICES = [
        ('authentic', 'Authentique'),
        ('counterfeit', 'Contrefaçon'),
        ('unknown', 'Inconnu'),
    ]
    raw_code = models.TextField()
    result = models.CharField(max_length=20, choices=RESULT_CHOICES)
    scanned_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='scans')
    qrcode = models.ForeignKey(QRCode, on_delete=models.SET_NULL, null=True, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)