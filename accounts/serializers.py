from rest_framework import serializers
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken

from .models import User
from casinos.models import Casino
from casinos.serializers import CasinoSerializer



class UserSerializer(serializers.ModelSerializer):
    casinos = CasinoSerializer(many=True, read_only=True)
    casino_name = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=6)

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "username",
            "password",
            "role",
            "staff_code",
            "casinos",
            "casino_name",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined", "casino_name", "casinos"]

    def get_casino_name(self, obj):
        first_casino = obj.casinos.first()
        return first_casino.name if first_casino else None

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance


class CreateUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    casinos = serializers.PrimaryKeyRelatedField(
        queryset=Casino.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "username",
            "staff_code",
            "password",
            "role",
            "casinos",
            "is_active",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        request = self.context["request"]
        creator = request.user

        role = attrs.get("role")
        selected_casinos = attrs.get("casinos", [])

        if creator.role == "super_admin":
            if role == "super_admin":
                raise serializers.ValidationError({
                    "role": "Use management command/admin to create another super admin."
                })

            if role in ["casino_admin", "staff"] and not selected_casinos:
                raise serializers.ValidationError({
                    "casinos": "At least one casino must be assigned."
                })

        elif creator.role == "casino_admin":
            if role != "staff":
                raise serializers.ValidationError({
                    "role": "Casino admin can only create staff."
                })

            creator_casinos = list(creator.casinos.all())
            if not creator_casinos:
                raise serializers.ValidationError({
                    "detail": "Casino admin is not assigned to any casino."
                })

            attrs["casinos"] = creator_casinos

        else:
            raise serializers.ValidationError({
                "detail": "You do not have permission to create users."
            })

        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        casinos = validated_data.pop("casinos", [])

        user = User.objects.create_user(password=password, **validated_data)

        if casinos:
            user.casinos.set(casinos)

        return user


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({
                "confirm_password": "Passwords do not match."
            })
        return attrs


class UpdateProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "email", "phone"]

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Full name is required.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        user = self.instance

        qs = User.objects.filter(email__iexact=value).exclude(pk=user.pk)
        if qs.exists():
            raise serializers.ValidationError("This email is already in use.")

        return value

    def validate_phone(self, value):
        if value is None:
            return ""
        return value.strip()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def get_user_casinos(self, user):
        if user.role == "super_admin":
            casinos = Casino.objects.all()
        else:
            casinos = user.casinos.all()

        return [
            {
                "id": str(casino.id),
                "name": casino.name,
                "chatwoot_inbox_id": casino.chatwoot_inbox_id,
            }
            for casino in casinos
        ]

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        if user.role == "super_admin":
            casinos = Casino.objects.all()
        else:
            casinos = user.casinos.all()

        first_casino = casinos.first()

        token["token_version"] = user.token_version
        token["user_id"] = str(user.id)
        token["role"] = user.role
        token["full_name"] = user.full_name
        token["casinos"] = [
            {
                "id": str(casino.id),
                "name": casino.name,
                "chatwoot_inbox_id": casino.chatwoot_inbox_id,
            }
            for casino in casinos
        ]

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        if self.user.role == "super_admin":
            casinos = Casino.objects.all()
        else:
            casinos = self.user.casinos.all()

        first_casino = casinos.first()

        data["user"] = {
            "id": str(self.user.id),
            "full_name": self.user.full_name,
            "email": self.user.email,
            "role": self.user.role,
            "casino_id": str(first_casino.id) if first_casino else None,
            "casino_name": first_casino.name if first_casino else None,
            "casinos": [
                {
                    "id": str(casino.id),
                    "name": casino.name,
                    "chatwoot_inbox_id": casino.chatwoot_inbox_id,
                }
                for casino in casinos
            ],
        }

        return data


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.get("user_id")
        token_version = refresh.get("token_version", 0)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise InvalidToken("User not found")

        if user.token_version != token_version:
            raise InvalidToken("Session expired. Please log in again.")

        return super().validate(attrs)