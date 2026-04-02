from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import Customer, Transaction
from casinos.models import Casino

class CustomerSerializer(serializers.ModelSerializer):
    casino_name = serializers.CharField(source="casino.name", read_only=True)
    casino = serializers.PrimaryKeyRelatedField(
        queryset=Casino.objects.all(),
        required=False
    )

    txn_count = serializers.IntegerField(read_only=True)
    last_activity = serializers.SerializerMethodField()
    total_deposit = serializers.SerializerMethodField()
    total_withdrawal = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id",
            "fullname",
            "username",
            "phone",
            "email",
            "notes",
            "casino",
            "fb_user_id",
            "casino_name",
            "last_activity",
            "total_deposit",
            "total_withdrawal",
            "tags",
            "txn_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "casino_name",
            "last_activity",
            "total_deposit",
            "total_withdrawal",
            "tags",
            "created_at",
            "updated_at",
        ]

    def get_last_activity(self, obj):
        last_tx = obj.transactions.order_by("-date", "-id").first()
        return last_tx.date if last_tx else None

    def get_total_deposit(self, obj):
        total = obj.transactions.filter(
            type=Transaction.TransactionType.DEPOSIT
        ).aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0.00")

    def get_total_withdrawal(self, obj):
        total = obj.transactions.filter(
            type=Transaction.TransactionType.WITHDRAW
        ).aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0.00")

    def get_tags(self, obj):
        tags = []

        today = timezone.localdate()
        deposits = list(
            obj.transactions.filter(
                type=Transaction.TransactionType.DEPOSIT
            ).order_by("date")
        )

        all_transactions = list(obj.transactions.order_by("-date", "-id"))
        last_tx = all_transactions[0] if all_transactions else None

        if last_tx:
            days_since_last = (today - last_tx.date).days
            if days_since_last <= 4:
                tags.append("active")
            elif days_since_last > 5:
                tags.append("inactive")
        else:
            tags.append("inactive")

        is_regular = False
        if len(deposits) >= 2:
            day_gaps = []
            for i in range(1, len(deposits)):
                gap = (deposits[i].date - deposits[i - 1].date).days
                day_gaps.append(gap)

            if day_gaps and all(gap in [1, 2] for gap in day_gaps):
                is_regular = True
                tags.append("regular")

        if is_regular and deposits:
            if all(tx.amount > Decimal("50") for tx in deposits):
                tags.append("vip")

        return tags
class TransactionSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.fullname", read_only=True)
    casino_name = serializers.CharField(source="casino.name", read_only=True)
    platform_name = serializers.CharField(source="platform.name", read_only=True)
    payment_method_name = serializers.CharField(source="payment_method.name", read_only=True)
    added_by_name = serializers.CharField(source="added_by.full_name", read_only=True)

    casino = serializers.PrimaryKeyRelatedField(
        queryset=Casino.objects.all(),
        required=False
    )

    class Meta:
        model = Transaction
        fields = [
            "id",
            "customer",
            "customer_name",
            "casino",
            "casino_name",
            "added_by",
            "added_by_name",
            "amount",
            "date",
            "notes",
            "type",
            "platform",
            "platform_name",
            "payment_method",
            "payment_method_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "customer_name",
            "casino_name",
            "added_by",
            "added_by_name",
            "platform_name",
            "payment_method_name",
            "created_at",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        casino = attrs.get("casino", getattr(self.instance, "casino", None))

        # auto-force casino for casino_admin / staff
        if user.role in ["casino_admin", "staff"]:
            if not user.casino:
                raise serializers.ValidationError({
                    "casino": "User is not assigned to any casino."
                })

            attrs["casino"] = user.casino
            casino = user.casino

        # require casino only for super_admin
        elif user.role == "super_admin":
            if not casino:
                raise serializers.ValidationError({
                    "casino": "Casino is required for super admin."
                })

        # customer must belong to same casino
        if customer and casino and customer.casino_id != casino.id:
            raise serializers.ValidationError({
                "customer": "Customer does not belong to the selected casino."
            })

        # restricted roles can only use own casino customers
        if user.role in ["casino_admin", "staff"] and customer:
            if customer.casino_id != user.casino_id:
                raise serializers.ValidationError({
                    "customer": "You can only use customers from your own casino."
                })

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["added_by"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user

        if user.role in ["casino_admin", "staff"]:
            validated_data["casino"] = user.casino

        return super().update(instance, validated_data)