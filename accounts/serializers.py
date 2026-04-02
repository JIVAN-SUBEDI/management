from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken
from .models import User


class UserSerializer(serializers.ModelSerializer):
    casino_name = serializers.CharField(source="casino.name", read_only=True)
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
            "casino",
            "casino_name",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined", "casino_name"]

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
            "casino",
            "is_active",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        request = self.context["request"]
        creator = request.user

        role = attrs.get("role")
        selected_casino = attrs.get("casino")

        if creator.role == "super_admin":
            if role == "super_admin":
                raise serializers.ValidationError({
                    "role": "Use management command/admin to create another super admin."
                })

            if role in ["casino_admin", "staff"] and not selected_casino:
                raise serializers.ValidationError({
                    "casino": "Casino must be assigned by super admin."
                })

        elif creator.role == "casino_admin":
            if role != "staff":
                raise serializers.ValidationError({
                    "role": "Casino admin can only create staff."
                })

            # casino admin does not choose arbitrary casino
            attrs["casino"] = creator.casino

        else:
            raise serializers.ValidationError({
                "detail": "You do not have permission to create users."
            })

        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)



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
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["token_version"] = user.token_version
        token["user_id"] = str(user.id)
        token["role"] = user.role
        token["full_name"] = user.full_name
        token["casino_id"] = user.casino_id
        token["casino_name"] = user.casino.name if user.casino else None
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        data["user"] = {
            "id": self.user.id,
            "full_name": self.user.full_name,
            "email": self.user.email,
            "role": self.user.role,
            "casino_id": self.user.casino_id,
            "casino_name": self.user.casino.name if self.user.casino else None,
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