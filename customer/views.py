from rest_framework import permissions, viewsets,status as drf_status

from .models import Customer, Transaction
from .serializers import CustomerSerializer, TransactionSerializer
from rest_framework.pagination import PageNumberPagination
from django.db.models import Count
from rest_framework.response import Response
from rest_framework.views import APIView
from decimal import Decimal
class TransactionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

from rest_framework.exceptions import ValidationError, PermissionDenied

class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Customer.objects.select_related("casino").prefetch_related(
            "transactions"
        ).annotate(
            txn_count=Count("transactions")
        )

        if user.role == "super_admin":
            return queryset

        if user.role in ["casino_admin", "staff"]:
            return queryset.filter(casino=user.casino)

        return Customer.objects.none()

    def perform_create(self, serializer):
        user = self.request.user

        if user.role in ["casino_admin", "staff"]:
            serializer.save(casino=user.casino)
            return

        if user.role == "super_admin":
            casino = serializer.validated_data.get("casino")
            if not casino:
                raise ValidationError({"casino": "Casino is required for super admin."})
            serializer.save()
            return

        raise PermissionDenied("You are not allowed to create customers.")


class TransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = TransactionPagination
    def get_queryset(self):
        user = self.request.user
        queryset = Transaction.objects.select_related(
            "customer", "casino", "platform", "payment_method", "added_by"
        ).order_by("-date", "-id")

        if user.role == "super_admin":
            pass

        elif user.role == "casino_admin":
            queryset = queryset.filter(casino=user.casino)

        else:
            queryset = queryset.filter(casino=user.casino, added_by=user)

        search = self.request.query_params.get("search")
        tx_type = self.request.query_params.get("type")

        if search:
            queryset = queryset.filter(customer__fullname__icontains=search)

        if tx_type in ["deposit", "withdraw"]:
            queryset = queryset.filter(type=tx_type)

        return queryset

    def perform_create(self, serializer):
        user = self.request.user

        if user.role == "super_admin":

            serializer.save(added_by=user)
        
        elif user.role == "casino_admin":
            serializer.save(added_by=user, casino=user.casino)
        
        elif user.role == "staff":
            serializer.save(added_by=user, casino=user.casino)
        
        else:
            # Handle other roles or unauthorized
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to create transactions")

    def perform_update(self, serializer):
        serializer.save()
    
class CampaignSegmentsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self, request):
        user = request.user
        queryset = Customer.objects.select_related("casino").prefetch_related("transactions")

        if user.role == "super_admin":
            return queryset

        if user.role in ["casino_admin", "staff"]:
            return queryset.filter(casino=user.casino)

        return Customer.objects.none()

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
            "last_activity": customer.last_activity if hasattr(customer, "last_activity") else None,
            "tags": customer.tags if hasattr(customer, "tags") else [],
            "status": customer.status if hasattr(customer, "status") else "",
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
            tags = [str(tag).lower() for tag in (getattr(customer, "tags", []) or [])]
            status = str(getattr(customer, "status", "") or "").lower()

            item = self.serialize_customer(customer)

            if "vip" in tags or status == "vip":
                segments["vip_players"].append(item)

            if ("regular_player" in tags or status == "regular" or status == "active") and "vip" not in tags:
                segments["regular_players"].append(item)

            if total_deposit > Decimal("30000"):
                segments["high_deposit_players"].append(item)

            if total_withdrawal > Decimal("20000"):
                segments["high_withdrawal_players"].append(item)

            if "inactive" in tags or status == "inactive":
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