from django.db import models
from django.conf import settings
from casinos.models import Casino, Platforms, PaymentMethod


User = settings.AUTH_USER_MODEL


class Customer(models.Model):
    fullname = models.CharField(max_length=255)
    username = models.CharField(max_length=255, unique=True)
    fb_user_id = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    casino = models.ForeignKey(
        Casino,
        on_delete=models.CASCADE,
        related_name="customers"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fullname"]

    def __str__(self):
        return f"{self.fullname} ({self.username})"


class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAW = "withdraw", "Withdraw"

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="transactions"
    )
    casino = models.ForeignKey(
        Casino,
        on_delete=models.CASCADE,
        related_name="transactions"
    )
    added_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="added_transactions"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    notes = models.TextField(blank=True, null=True)
    type = models.CharField(
        max_length=20,
        choices=TransactionType.choices
    )
    platform = models.ForeignKey(
        Platforms,
        on_delete=models.SET_NULL,
        null=True,
        related_name="transactions"
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        related_name="transactions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.customer.fullname} - {self.type} - {self.amount}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if not self.customer_id or not self.casino_id:
            return


        if self.customer.casino_id != self.casino_id:
            raise ValidationError({
                "casino": "Transaction casino must match customer casino."
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class FacebookOutgoingMessageLog(models.Model):
    casino = models.ForeignKey(
        Casino,
        on_delete=models.CASCADE,
        related_name="fb_outgoing_logs"
    )
    staff = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="fb_outgoing_logs"
    )
    page_id = models.CharField(max_length=100)
    recipient_fb_user_id = models.CharField(max_length=100)
    message_text = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    matched = models.BooleanField(default=False)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.staff} -> {self.recipient_fb_user_id} ({self.sent_at})"