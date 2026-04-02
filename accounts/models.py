from django.db import models
from django.db.models import Q
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError

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

    casino = models.ForeignKey(
        "casinos.Casino",
        on_delete=models.SET_NULL,
        null=True,
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
        constraints = [
            models.UniqueConstraint(
                fields=["casino"],
                condition=Q(role="casino_admin"),
                name="unique_casino_admin_per_casino",
            )
        ]

    def clean(self):
        if self.role == "super_admin" and self.casino is not None:
            raise ValidationError({"casino": "Super admin cannot belong to a casino."})

        if self.role in ["casino_admin", "staff"] and self.casino is None:
            raise ValidationError({"casino": "Casino is required for this role."})

    def save(self, *args, **kwargs):
        if self.role == "super_admin":
            self.casino = None
            self.is_staff = True
        elif self.role == "casino_admin":
            self.is_staff = True

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} - {self.email}"