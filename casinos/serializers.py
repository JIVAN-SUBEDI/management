from rest_framework import serializers
from .models import Casino,PaymentMethod,Platforms


class CasinoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Casino
        fields = [
            "id",
            "name",
            "code",
            "chatwoot_inbox_id",
            "contact_email",
            "contact_phone",
            "address",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = '__all__'
class PlatformsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platforms
        fields = '__all__'