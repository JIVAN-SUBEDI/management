from decimal import Decimal

from django.db.models import Count
from rest_framework import permissions, viewsets, status as drf_status
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from casinos.models import Casino
from .models import Customer, Transaction
from .serializers import CustomerSerializer, TransactionSerializer


class TransactionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def get_requested_casino(user, request):
    casino_id = (
        request.data.get("casino")
        or request.data.get("casino_id")
        or request.query_params.get("casino_id")
    )

    if not casino_id:
        raise ValidationError({"casino_id": "casino_id is required."})

    if user.role == "super_admin":
        casino = Casino.objects.filter(id=casino_id).first()
    else:
        casino = user.casinos.filter(id=casino_id).first()

    if not casino:
        raise PermissionDenied("You do not have access to this casino.")

    return casino


def user_has_casino_access(user, casino_id):
    if user.role == "super_admin":
        return Casino.objects.filter(id=casino_id).exists()

    return user.casinos.filter(id=casino_id).exists()


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        casino_id = self.request.query_params.get("casino_id")

        queryset = (
            Customer.objects.select_related("casino")
            .prefetch_related("transactions")
            .annotate(txn_count=Count("transactions"))
        )

        if casino_id:
            if not user_has_casino_access(user, casino_id):
                return Customer.objects.none()

            return queryset.filter(casino_id=casino_id)

        if user.role == "super_admin":
            return queryset

        return queryset.filter(casino__in=user.casinos.all())

    def perform_create(self, serializer):
        casino = get_requested_casino(self.request.user, self.request)
        serializer.save(casino=casino)

    def perform_update(self, serializer):
        user = self.request.user
        instance = self.get_object()

        if not user_has_casino_access(user, instance.casino_id):
            raise PermissionDenied("You do not have access to this casino.")

        serializer.save()


class TransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = TransactionPagination

    def get_queryset(self):
        user = self.request.user
        casino_id = self.request.query_params.get("casino_id")

        queryset = Transaction.objects.select_related(
            "customer",
            "casino",
            "platform",
            "payment_method",
            "added_by",
        ).order_by("-date", "-id")

        if casino_id:
            if not user_has_casino_access(user, casino_id):
                return Transaction.objects.none()

            queryset = queryset.filter(casino_id=casino_id)
        else:
            if user.role == "super_admin":
                pass
            elif user.role == "casino_admin":
                queryset = queryset.filter(casino__in=user.casinos.all())
            else:
                queryset = queryset.filter(
                    casino__in=user.casinos.all(),
                    added_by=user,
                )

        search = self.request.query_params.get("search")
        tx_type = self.request.query_params.get("type")

        if search:
            queryset = queryset.filter(customer__fullname__icontains=search)

        if tx_type in ["deposit", "withdraw"]:
            queryset = queryset.filter(type=tx_type)

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        casino = get_requested_casino(user, self.request)
        serializer.save(added_by=user, casino=casino)

    def perform_update(self, serializer):
        user = self.request.user
        instance = self.get_object()

        if not user_has_casino_access(user, instance.casino_id):
            raise PermissionDenied("You do not have access to this casino.")

        serializer.save()


class CampaignSegmentsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self, request):
        user = request.user
        casino_id = request.query_params.get("casino_id")

        queryset = Customer.objects.select_related("casino").prefetch_related(
            "transactions"
        )

        if casino_id:
            if not user_has_casino_access(user, casino_id):
                return Customer.objects.none()

            return queryset.filter(casino_id=casino_id)

        if user.role == "super_admin":
            return queryset

        return queryset.filter(casino__in=user.casinos.all())

    def serialize_customer(self, customer):
        total_deposit = Decimal(getattr(customer, "total_deposit", 0) or 0)
        total_withdrawal = Decimal(getattr(customer, "total_withdrawal", 0) or 0)

        return {
            "id": customer.id,
            "fullname": customer.fullname,
            "username": customer.username,
            "casino_name": customer.casino.name if customer.casino else "",
            "total_deposit": float(total_deposit),
            "total_withdrawal": float(total_withdrawal),
            "last_activity": getattr(customer, "last_activity", None),
            "tags": getattr(customer, "tags", []) or [],
            "status": getattr(customer, "status", "") or "",
        }

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset(request)

        customers = list(queryset)

        segments = {
            "vip_players": [],
            "regular_players": [],
            "high_deposit_players": [],
            "high_withdrawal_players": [],
            "inactive_players": [],
        }

        for customer in customers:
            total_deposit = Decimal(getattr(customer, "total_deposit", 0) or 0)
            total_withdrawal = Decimal(getattr(customer, "total_withdrawal", 0) or 0)

            tags = [
                str(tag).lower()
                for tag in (getattr(customer, "tags", []) or [])
            ]
            status_value = str(getattr(customer, "status", "") or "").lower()

            item = self.serialize_customer(customer)

            if "vip" in tags or status_value == "vip":
                segments["vip_players"].append(item)

            if (
                "regular_player" in tags
                or status_value == "regular"
                or status_value == "active"
            ) and "vip" not in tags:
                segments["regular_players"].append(item)

            if total_deposit > Decimal("30000"):
                segments["high_deposit_players"].append(item)

            if total_withdrawal > Decimal("20000"):
                segments["high_withdrawal_players"].append(item)

            if "inactive" in tags or status_value == "inactive":
                segments["inactive_players"].append(item)

        response = {
            "segments": {
                "vip_players": {
                    "name": "VIP Players",
                    "description": "High-value customers with VIP status",
                    "count": len(segments["vip_players"]),
                    "players": segments["vip_players"],
                },
                "regular_players": {
                    "name": "Regular Players",
                    "description": "Active regular customers",
                    "count": len(segments["regular_players"]),
                    "players": segments["regular_players"],
                },
                "high_deposit_players": {
                    "name": "High Deposit Players",
                    "description": "Players with deposits over $30,000",
                    "count": len(segments["high_deposit_players"]),
                    "players": segments["high_deposit_players"],
                },
                "high_withdrawal_players": {
                    "name": "High Withdrawal Players",
                    "description": "Players with withdrawals over $20,000",
                    "count": len(segments["high_withdrawal_players"]),
                    "players": segments["high_withdrawal_players"],
                },
                "inactive_players": {
                    "name": "Inactive Players",
                    "description": "Players with no recent activity",
                    "count": len(segments["inactive_players"]),
                    "players": segments["inactive_players"],
                },
            }
        }

        return Response(response, status=drf_status.HTTP_200_OK)