from django.db import models


class Casino(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=50, unique=True)
    contact_email = models.EmailField(blank=True, null=True)
    contact_phone = models.CharField(max_length=30, blank=True, null=True)
    chatwoot_inbox_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"
class PaymentMethod(models.Model):
    name = models.CharField(max_length=150, unique=True)
class Platforms(models.Model):
    name = models.CharField(max_length=150, unique=True)