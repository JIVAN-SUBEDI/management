from django.db import models
from django.db.models import Q
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.conf import settings
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ("super_admin", "Super Admin"),
        ("casino_admin", "Casino Admin"),
        ("staff", "Staff"),
    )

    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    username = models.CharField(max_length=80, unique=True, blank=True, null=True)
    staff_code = models.CharField(max_length=50, blank=True, null=True, unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    fb_user_access_token = models.TextField(blank=True, null=True)
    fb_oauth_state = models.CharField(max_length=255, null=True, blank=True)

    casinos = models.ManyToManyField(
        "casinos.Casino",
        blank=True,
        related_name="users",
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    token_version = models.IntegerField(default=1)
    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["-date_joined"]


    # def clean(self):
    #     if self.role == "super_admin" and self.casinos.exists():
    #         raise ValidationError({"casinos": "Super admin cannot belong to any casino."})

    #     if self.role in ["casino_admin", "staff"] and not self.casinos.exists():
    #         raise ValidationError({"casinos": "At least one casino is required for this role."})

    def save(self, *args, **kwargs):
        if self.role == "super_admin":
            self.is_staff = True
        elif self.role == "casino_admin":
            self.is_staff = True

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} - {self.email}"
class UserDevice(models.Model):
    DEVICE_TYPE_CHOICES = (
        ("android", "Android"),
        ("ios", "iOS"),
        ("web", "Web"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="devices"
    )

    fcm_token = models.TextField(unique=True)

    device_type = models.CharField(
        max_length=10,
        choices=DEVICE_TYPE_CHOICES,
        blank=True,
        null=True
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} - {self.device_type}"