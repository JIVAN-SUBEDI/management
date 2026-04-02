from datetime import timedelta, date
from decimal import Decimal

from django.db.models import Count, Sum, Q,Avg
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from customer.models import Customer, Transaction,PaymentMethod,Platforms
from casinos.models import Casino
from django.contrib.auth import get_user_model
User = get_user_model()
class CasinoAdminDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_date_range(self, request):
        today = timezone.localdate()
        period = request.query_params.get("period", "today")

        if period == "today":
            return period, today, today

        if period == "week":
            start_date = today - timedelta(days=6)
            return period, start_date, today

        if period == "month":
            start_date = today.replace(day=1)
            return period, start_date, today

        if period == "custom":
            start_str = request.query_params.get("start_date")
            end_str = request.query_params.get("end_date")

            if not start_str or not end_str:
                return None, None, None

            try:
                start_date = date.fromisoformat(start_str)
                end_date = date.fromisoformat(end_str)
            except ValueError:
                return None, None, None

            if start_date > end_date:
                return None, None, None

            return period, start_date, end_date

        return None, None, None

    def build_revenue_overview(self, transactions, period, start_date, end_date):
        revenue_overview = []

        if period == "today":
            day_qs = transactions.filter(date=start_date)
            deposits = day_qs.filter(
                type=Transaction.TransactionType.DEPOSIT
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            withdrawals = day_qs.filter(
                type=Transaction.TransactionType.WITHDRAW
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            revenue_overview.append({
                "label": start_date.strftime("%d %b"),
                "deposits": float(deposits),
                "withdrawals": float(withdrawals),
            })
            return revenue_overview

        current = start_date
        while current <= end_date:
            day_qs = transactions.filter(date=current)

            deposits = day_qs.filter(
                type=Transaction.TransactionType.DEPOSIT
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            withdrawals = day_qs.filter(
                type=Transaction.TransactionType.WITHDRAW
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            revenue_overview.append({
                "label": current.strftime("%d %b"),
                "deposits": float(deposits),
                "withdrawals": float(withdrawals),
            })

            current += timedelta(days=1)

        return revenue_overview

    def get(self, request, *args, **kwargs):
        user = request.user

        if user.role not in ["casino_admin", "staff"]:
            return Response(
                {"detail": "Only casino admin or staff can access this dashboard."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not user.casino:
            return Response(
                {"detail": "User is not assigned to any casino."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        period, start_date, end_date = self.get_date_range(request)
        if not period:
            return Response(
                {
                    "detail": "Invalid date filter. Use period=today|week|month|custom. "
                              "For custom, provide start_date and end_date in YYYY-MM-DD format."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        casino = user.casino
        today = timezone.localdate()
        if user.role == "casino_admin":
            all_transactions = Transaction.objects.filter(casino=casino)
        elif user.role == "staff":
            all_transactions = Transaction.objects.filter(casino=casino, added_by=user)
        else:
            return Response(
                {"detail": "You do not have permission to access this dashboard."},
                status=403,
            )

        filtered_transactions = all_transactions.filter(date__gte=start_date, date__lte=end_date)
        customers = Customer.objects.filter(casino=casino)

        total_deposits = filtered_transactions.filter(
            type=Transaction.TransactionType.DEPOSIT
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_withdrawals = filtered_transactions.filter(
            type=Transaction.TransactionType.WITHDRAW
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        net_profit = total_deposits - total_withdrawals

        # still useful as "today" cards even if period is week/month/custom
        todays_deposits = all_transactions.filter(
            type=Transaction.TransactionType.DEPOSIT,
            date=today,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        todays_withdrawals = all_transactions.filter(
            type=Transaction.TransactionType.WITHDRAW,
            date=today,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        active_players = customers.filter(
            transactions__date__gte=today - timedelta(days=4)
        ).distinct().count()

        revenue_overview = self.build_revenue_overview(
            filtered_transactions, period, start_date, end_date
        )

        payment_method_breakdown = list(
            filtered_transactions.values("payment_method__name")
            .annotate(value=Sum("amount"))
            .order_by("-value")
        )
        payment_method_breakdown = [
            {
                "name": row["payment_method__name"],
                "value": float(row["value"] or 0),
            }
            for row in payment_method_breakdown
        ]

        top_players_qs = customers.annotate(
            total_deposit=Sum(
                "transactions__amount",
                filter=Q(
                    transactions__type=Transaction.TransactionType.DEPOSIT,
                    transactions__date__gte=start_date,
                    transactions__date__lte=end_date,
                ),
            ),
            total_withdrawal=Sum(
                "transactions__amount",
                filter=Q(
                    transactions__type=Transaction.TransactionType.WITHDRAW,
                    transactions__date__gte=start_date,
                    transactions__date__lte=end_date,
                ),
            ),
            tx_count=Count(
                "transactions",
                filter=Q(
                    transactions__date__gte=start_date,
                    transactions__date__lte=end_date,
                ),
            ),
        ).order_by("-total_deposit")[:10]

        top_players = []
        for c in top_players_qs:
            deposit = c.total_deposit or Decimal("0.00")
            withdrawal = c.total_withdrawal or Decimal("0.00")
            net = deposit - withdrawal

            customer_last_tx = c.transactions.order_by("-date", "-id").first()
            if customer_last_tx:
                days_since = (today - customer_last_tx.date).days
                player_status = "inactive" if days_since > 5 else "active"
            else:
                player_status = "inactive"

            top_players.append({
                "id": c.id,
                "name": c.fullname,
                "total_deposit": float(deposit),
                "total_withdrawal": float(withdrawal),
                "net": float(net),
                "status": player_status,
            })

        data = {
            "casino": {
                "id": casino.id,
                "name": casino.name,
                "code": casino.code,
            },
            "filters": {
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
            },
            "stats": {
                "total_deposits": float(total_deposits),
                "total_withdrawals": float(total_withdrawals),
                "net_profit": float(net_profit),
                "active_players": active_players,
                "todays_deposits": float(todays_deposits),
                "todays_withdrawals": float(todays_withdrawals),
            },
            "charts": {
                "revenue_overview": revenue_overview,
                "payment_method_breakdown": payment_method_breakdown,
            },
            "top_players": top_players,
        }

        return Response(data)



class AnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_date_range(self, request):
        today = timezone.localdate()
        period = request.query_params.get("period", "month")

        if period == "today":
            return period, today, today

        if period == "week":
            return period, today - timedelta(days=6), today

        if period == "month":
            return period, today.replace(day=1), today

        if period == "custom":
            start_str = request.query_params.get("start_date")
            end_str = request.query_params.get("end_date")

            if not start_str or not end_str:
                return None, None, None

            try:
                start_date = date.fromisoformat(start_str)
                end_date = date.fromisoformat(end_str)
            except ValueError:
                return None, None, None

            if start_date > end_date:
                return None, None, None

            return period, start_date, end_date

        return None, None, None

    def build_daily_deposits(self, transactions, start_date, end_date):
        rows = []
        current = start_date
        while current <= end_date:
            amount = transactions.filter(
                type=Transaction.TransactionType.DEPOSIT,
                date=current,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            rows.append({
                "day": current.strftime("%d %b"),
                "amount": float(amount),
            })
            current += timedelta(days=1)
        return rows

    def build_revenue_overview(self, transactions, start_date, end_date):
        rows = []
        current = start_date
        while current <= end_date:
            deposits = transactions.filter(
                type=Transaction.TransactionType.DEPOSIT,
                date=current,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            withdrawals = transactions.filter(
                type=Transaction.TransactionType.WITHDRAW,
                date=current,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            rows.append({
                "month": current.strftime("%d %b"),
                "deposits": float(deposits),
                "withdrawals": float(withdrawals),
            })
            current += timedelta(days=1)
        return rows

    def get(self, request, *args, **kwargs):
        user = request.user

        if user.role == "staff":
            return Response(
                {"detail": "Staff cannot access analytics."},
                status=status.HTTP_403_FORBIDDEN,
            )

        period, start_date, end_date = self.get_date_range(request)
        if not period:
            return Response(
                {"detail": "Invalid filter. Use today, week, month, or custom with start_date and end_date."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        casino_id = request.query_params.get("casino")

        if user.role == "casino_admin":
            selected_casino = user.casino
            if not selected_casino:
                return Response(
                    {"detail": "Casino admin is not assigned to a casino."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            transactions = Transaction.objects.filter(casino=selected_casino)
            customers = Customer.objects.filter(casino=selected_casino)
            scope = "single"
        else:
            # super_admin
            if casino_id:
                try:
                    selected_casino = Casino.objects.get(pk=casino_id)
                except Casino.DoesNotExist:
                    return Response(
                        {"detail": "Casino not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                transactions = Transaction.objects.filter(casino=selected_casino)
                customers = Customer.objects.filter(casino=selected_casino)
                scope = "single"
            else:
                selected_casino = None
                transactions = Transaction.objects.all()
                customers = Customer.objects.all()
                scope = "all"

        filtered_transactions = transactions.filter(date__gte=start_date, date__lte=end_date)

        deposits_per_day = self.build_daily_deposits(filtered_transactions, start_date, end_date)
        revenue_overview = self.build_revenue_overview(filtered_transactions, start_date, end_date)

        platform_breakdown_qs = (
            filtered_transactions.values("platform__name")
            .annotate(value=Sum("amount"))
            .order_by("-value")
        )
        platform_breakdown = [
            {"name": row["platform__name"], "value": float(row["value"] or 0)}
            for row in platform_breakdown_qs
        ]

        payment_method_qs = (
            filtered_transactions.values("payment_method__name")
            .annotate(value=Sum("amount"))
            .order_by("-value")
        )
        payment_method_breakdown = [
            {"name": row["payment_method__name"], "value": float(row["value"] or 0)}
            for row in payment_method_qs
        ]

        profit_by_casino = []
        if user.role == "super_admin" and scope == "all":
            for casino in Casino.objects.filter(is_active=True).order_by("name"):
                casino_tx = filtered_transactions.filter(casino=casino)

                deposits = casino_tx.filter(
                    type=Transaction.TransactionType.DEPOSIT
                ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

                withdrawals = casino_tx.filter(
                    type=Transaction.TransactionType.WITHDRAW
                ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

                profit_by_casino.append({
                    "name": casino.name,
                    "profit": float(deposits - withdrawals),
                })

        data = {
            "scope": scope,
            "casino": (
                {
                    "id": selected_casino.id,
                    "name": selected_casino.name,
                    "code": selected_casino.code,
                }
                if selected_casino
                else None
            ),
            "filters": {
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
            },
            "charts": {
                "deposits_per_day": deposits_per_day,
                "revenue_overview": revenue_overview,
                "platform_breakdown": platform_breakdown,
                "payment_method_breakdown": payment_method_breakdown,
                "profit_by_casino": profit_by_casino,
            },
        }

        return Response(data)
class ReportsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_date_range(self, request):
        today = timezone.localdate()
        period = request.query_params.get("period", "week")

        if period == "today":
            return period, today, today

        if period == "week":
            return period, today - timedelta(days=6), today

        if period == "month":
            return period, today.replace(day=1), today

        if period == "year":
            return period, today.replace(month=1, day=1), today

        if period == "custom":
            start_str = request.query_params.get("start_date")
            end_str = request.query_params.get("end_date")

            if not start_str or not end_str:
                return None, None, None

            try:
                start_date = date.fromisoformat(start_str)
                end_date = date.fromisoformat(end_str)
            except ValueError:
                return None, None, None

            if start_date > end_date:
                return None, None, None

            return period, start_date, end_date

        return None, None, None

    def get(self, request, *args, **kwargs):
        user = request.user

        period, start_date, end_date = self.get_date_range(request)
        if not period:
            return Response(
                {"detail": "Invalid period or custom date range."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = Transaction.objects.select_related(
            "customer",
            "casino",
            "platform",
            "payment_method",
            "added_by",
        ).filter(date__gte=start_date, date__lte=end_date)

        # role-based access
        if user.role == "staff":
            queryset = queryset.filter(added_by=user)
        elif user.role == "casino_admin":
            queryset = queryset.filter(casino=user.casino)
        elif user.role == "super_admin":
            pass
        else:
            return Response(
                {"detail": "You do not have permission to access reports."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # optional filters
        casino_id = request.query_params.get("casino")
        staff_id = request.query_params.get("staff")
        platform_id = request.query_params.get("platform")
        payment_method_id = request.query_params.get("payment_method")
        tx_type = request.query_params.get("type")

        if user.role == "super_admin" and casino_id:
            queryset = queryset.filter(casino_id=casino_id)

        if user.role in ["super_admin", "casino_admin"] and staff_id:
            queryset = queryset.filter(added_by_id=staff_id)

        if platform_id:
            queryset = queryset.filter(platform_id=platform_id)

        if payment_method_id:
            queryset = queryset.filter(payment_method_id=payment_method_id)

        if tx_type in ["deposit", "withdraw"]:
            queryset = queryset.filter(type=tx_type)

        deposits_total = queryset.filter(
            type=Transaction.TransactionType.DEPOSIT
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        withdrawals_total = queryset.filter(
            type=Transaction.TransactionType.WITHDRAW
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        net_profit = deposits_total - withdrawals_total
        total_transactions = queryset.count()
        avg_transaction = queryset.aggregate(avg=Avg("amount"))["avg"] or Decimal("0.00")
        unique_players = queryset.values("customer_id").distinct().count()

        rows = [
            {
                "id": tx.id,
                "date": tx.date,
                "customer_name": tx.customer.fullname,
                "casino_name": tx.casino.name,
                "staff_name": tx.added_by.full_name if tx.added_by else None,
                "type": tx.type,
                "amount": float(tx.amount),
                "platform_name": tx.platform.name,
                "payment_method_name": tx.payment_method.name,
                "notes": tx.notes or "",
            }
            for tx in queryset.order_by("-date", "-id")
        ]

        data = {
            "filters": {
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "casino": casino_id,
                "staff": staff_id,
                "platform": platform_id,
                "payment_method": payment_method_id,
                "type": tx_type,
            },
            "summary": {
                "total_deposits": float(deposits_total),
                "total_withdrawals": float(withdrawals_total),
                "net_profit": float(net_profit),
                "total_transactions": total_transactions,
                "avg_transaction": float(avg_transaction),
                "unique_players": unique_players,
            },
            "rows": rows,
            "lookups": {
                "casinos": list(
                    Casino.objects.filter(is_active=True).values("id", "name")
                ) if user.role == "super_admin" else [],
                "staff": list(
                    User.objects.filter(
                        role__in=["casino_admin", "staff"],
                        casino=user.casino if user.role == "casino_admin" else None
                    ).values("id", "full_name", "role", "casino_id")
                ) if user.role == "casino_admin" else list(
                    User.objects.filter(
                        role__in=["casino_admin", "staff"]
                    ).values("id", "full_name", "role", "casino_id")
                ) if user.role == "super_admin" else [],
                "platforms": list(Platforms.objects.filter().values("id","name")),
                "payment_methods": list(PaymentMethod.objects.filter().values("id", "name")),
            },
            "generated_at": timezone.now(),
        }

        return Response(data)
class SuperAdminDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_date_range(self, request):
        today = timezone.localdate()
        period = request.query_params.get("period", "week")

        if period == "today":
            return period, today, today

        if period == "week":
            return period, today - timedelta(days=6), today

        if period == "month":
            return period, today.replace(day=1), today

        if period == "custom":
            start_str = request.query_params.get("start_date")
            end_str = request.query_params.get("end_date")

            if not start_str or not end_str:
                return None, None, None

            try:
                start_date = date.fromisoformat(start_str)
                end_date = date.fromisoformat(end_str)
            except ValueError:
                return None, None, None

            if start_date > end_date:
                return None, None, None

            return period, start_date, end_date

        return None, None, None

    def build_revenue_overview(self, transactions, start_date, end_date):
        rows = []
        current = start_date

        while current <= end_date:
            deposits = transactions.filter(
                type=Transaction.TransactionType.DEPOSIT,
                date=current,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            withdrawals = transactions.filter(
                type=Transaction.TransactionType.WITHDRAW,
                date=current,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            rows.append({
                "label": current.strftime("%d %b"),
                "deposits": float(deposits),
                "withdrawals": float(withdrawals),
            })

            current += timedelta(days=1)

        return rows

    def get(self, request, *args, **kwargs):
        user = request.user

        if user.role != "super_admin":
            return Response(
                {"detail": "Only super admin can access this dashboard."},
                status=status.HTTP_403_FORBIDDEN,
            )

        period, start_date, end_date = self.get_date_range(request)
        if not period:
            return Response(
                {"detail": "Invalid period or custom range."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        casino_id = request.query_params.get("casino")

        transactions = Transaction.objects.select_related(
            "customer",
            "casino",
            "platform",
            "payment_method",
            "added_by",
        ).all()

        customers = Customer.objects.all()
        casinos = Casino.objects.all()
        staff_users = User.objects.filter(role__in=["casino_admin", "staff"])

        if casino_id:
            transactions = transactions.filter(casino_id=casino_id)
            customers = customers.filter(casino_id=casino_id)
            casinos = casinos.filter(id=casino_id)
            staff_users = staff_users.filter(casino_id=casino_id)

        filtered_transactions = transactions.filter(date__gte=start_date, date__lte=end_date)

        total_deposits = filtered_transactions.filter(
            type=Transaction.TransactionType.DEPOSIT
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_withdrawals = filtered_transactions.filter(
            type=Transaction.TransactionType.WITHDRAW
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        net_profit = total_deposits - total_withdrawals

        active_players = customers.filter(
            transactions__date__gte=timezone.localdate() - timedelta(days=4)
        ).distinct().count()

        total_staff = staff_users.count()

        revenue_overview = self.build_revenue_overview(
            filtered_transactions,
            start_date,
            end_date,
        )

        profit_by_casino = []
        for casino in Casino.objects.all().order_by("name"):
            casino_tx = filtered_transactions.filter(casino=casino)

            deposits = casino_tx.filter(
                type=Transaction.TransactionType.DEPOSIT
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            withdrawals = casino_tx.filter(
                type=Transaction.TransactionType.WITHDRAW
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            profit_by_casino.append({
                "name": casino.name,
                "profit": float(deposits - withdrawals),
            })

        casino_performance_qs = Customer.objects.values(
            "casino_id",
            "casino__name",
        ).annotate(
            players=Count("id"),
            total_deposits=Sum(
                "transactions__amount",
                filter=Q(
                    transactions__type=Transaction.TransactionType.DEPOSIT,
                    transactions__date__gte=start_date,
                    transactions__date__lte=end_date,
                ),
            ),
            total_withdrawals=Sum(
                "transactions__amount",
                filter=Q(
                    transactions__type=Transaction.TransactionType.WITHDRAW,
                    transactions__date__gte=start_date,
                    transactions__date__lte=end_date,
                ),
            ),
        ).order_by("casino__name")

        casino_performance = []
        for row in casino_performance_qs:
            deposits = row["total_deposits"] or Decimal("0.00")
            withdrawals = row["total_withdrawals"] or Decimal("0.00")
            casino_performance.append({
                "casino_id": row["casino_id"],
                "name": row["casino__name"],
                "players": row["players"],
                "deposits": float(deposits),
                "withdrawals": float(withdrawals),
                "net_profit": float(deposits - withdrawals),
                "status": "active",
            })

        recent_transactions = [
            {
                "id": tx.id,
                "date": tx.date,
                "casino_name": tx.casino.name,
                "customer_name": tx.customer.fullname,
                "type": tx.type,
                "amount": float(tx.amount),
                "platform_name": tx.platform.name,
            }
            for tx in filtered_transactions.order_by("-date", "-id")[:8]
        ]

        data = {
            "filters": {
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "casino": casino_id,
            },
            "stats": {
                "total_casinos": Casino.objects.count() if not casino_id else 1,
                "total_deposits": float(total_deposits),
                "total_withdrawals": float(total_withdrawals),
                "net_profit": float(net_profit),
                "active_players": active_players,
                "total_staff": total_staff,
            },
            "charts": {
                "revenue_overview": revenue_overview,
                "profit_by_casino": profit_by_casino,
            },
            "casino_performance": casino_performance,
            "recent_transactions": recent_transactions,
            "lookups": {
                "casinos": list(Casino.objects.all().values("id", "name")),
            },
        }

        return Response(data)