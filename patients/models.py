from django.db import models


class PatientSearchHistory(models.Model):
    medicine_name = models.CharField(max_length=150)
    searched_at = models.DateTimeField(auto_now_add=True)

    patient = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='searches')
    found_pharmacy = models.ForeignKey('pharmacies.Pharmacy', on_delete=models.SET_NULL, null=True, blank=True)