from rest_framework import viewsets,status,permissions
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction as db_transaction
from decimal import Decimal,InvalidOperation
import re
from customer.models import Customer,Transaction
import json
from django.http import HttpResponse
import secrets
from .models import Casino,PaymentMethod,Platforms
from .serializers import CasinoSerializer,PaymentMethodSerializer,PlatformsSerializer
from backend.permissions import IsSuperAdmin, IsAuthenticatedReadOnlySuperAdminWrite
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils.text import slugify
from django.utils.timezone import localdate
import requests
from django.shortcuts import redirect
import hmac
import hashlib
User = get_user_model()

class CasinoViewSet(viewsets.ModelViewSet):
    queryset = Casino.objects.all()
    serializer_class = CasinoSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin]

class PaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated, IsAuthenticatedReadOnlySuperAdminWrite]
class PlatformsViewSet(viewsets.ModelViewSet):
    queryset = Platforms.objects.all()
    serializer_class = PlatformsSerializer
    permission_classes = [IsAuthenticated, IsAuthenticatedReadOnlySuperAdminWrite]

def username_to_fullname(username: str) -> str:
    parts = username.replace("-", " ").split()
    return " ".join(word.capitalize() for word in parts)


class DailyNoteParserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def normalize_username(self, username: str) -> str:
        return re.sub(r"\s+", " ", username.strip()).lower()

    def get_casino_id(self, request):
        user = request.user

        if user.role == "super_admin":
            casino_id = request.data.get("casino")
            if not casino_id:
                return None, Response(
                    {"detail": "Casino is required for super admin imports."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return int(casino_id), None

        if user.role in ["casino_admin", "staff"]:
            if not user.casino_id:
                return None, Response(
                    {"detail": "User is not assigned to any casino."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return int(user.casino_id), None

        return None, Response(
            {"detail": "You do not have permission to import notes."},
            status=status.HTTP_403_FORBIDDEN,
        )

    def parse_line(self, raw_line: str):
        line = raw_line.strip()
        if not line:
            return {"raw": raw_line, "error": "Empty line."}

        normalized = re.sub(r"\s+", " ", line).strip()
        lowered = normalized.lower()
        tokens = normalized.split(" ")

        if len(tokens) < 4:
            return {
                "raw": raw_line,
                "error": "Invalid format. Expected: username amount platform payment_method",
            }

        raw_username = tokens[0].strip()
        if not raw_username:
            return {"raw": raw_line, "error": "Username is required."}

        username = self.normalize_username(raw_username)

        is_withdraw = False
        if (
            "cash out" in lowered
            or "cashout" in lowered
            or "withdrawal" in lowered
            or "withdraw" in lowered
        ):
            is_withdraw = True

        amount_token = None
        amount_index = None

        for idx, token in enumerate(tokens[1:], start=1):
            cleaned = token.replace("$", "").replace(",", "")
            if re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
                amount_token = cleaned
                amount_index = idx
                break

        if amount_token is None:
            return {"raw": raw_line, "error": "Amount not found."}

        try:
            amount = Decimal(amount_token)
        except InvalidOperation:
            return {"raw": raw_line, "error": "Invalid amount."}

        if amount == 0:
            return {"raw": raw_line, "error": "Amount cannot be zero."}

        if amount < 0:
            is_withdraw = True
            amount = abs(amount)

        platform_token = None
        payment_token = None

        if amount_index is not None and len(tokens) > amount_index + 2:
            platform_token = tokens[amount_index + 1].strip().lower()
            payment_token = tokens[amount_index + 2].strip().lower()
        else:
            return {
                "raw": raw_line,
                "error": "Could not identify platform and payment method.",
            }

        return {
            "raw": raw_line,
            "username": username,  # normalized username
            "original_username": raw_username,  # optional, just for preview/debug
            "fullname": username_to_fullname(username),
            "amount": str(amount),
            "platform_token": platform_token,
            "payment_method_token": payment_token,
            "type": "withdraw" if is_withdraw else "deposit",
        }

    def post(self, request, *args, **kwargs):
        raw_text = request.data.get("raw_text", "")
        date_value = request.data.get("date")
        notes_prefix = request.data.get("notes_prefix", "")
        preview = request.data.get("preview", True)

        if not raw_text.strip():
            return Response(
                {"detail": "raw_text is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not date_value:
            return Response(
                {"detail": "date is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        casino_id, error_response = self.get_casino_id(request)
        if error_response:
            return error_response

        lines = [line for line in raw_text.splitlines() if line.strip()]
        parsed_rows = [self.parse_line(line) for line in lines]

        valid_rows = []
        error_rows = []

        for row in parsed_rows:
            if row.get("error"):
                error_rows.append(row)
                continue

            try:
                platform = Platforms.objects.get(name__iexact=row["platform_token"])
            except Platforms.DoesNotExist:
                error_rows.append(
                    {
                        **row,
                        "error": f"Platform '{row['platform_token']}' not found in database.",
                    }
                )
                continue

            try:
                payment_method = PaymentMethod.objects.get(
                    name__iexact=row["payment_method_token"]
                )
            except PaymentMethod.DoesNotExist:
                error_rows.append(
                    {
                        **row,
                        "error": f"Payment method '{row['payment_method_token']}' not found in database.",
                    }
                )
                continue

            row["platform_id"] = platform.id
            row["platform_name"] = platform.name
            row["payment_method_id"] = payment_method.id
            row["payment_method_name"] = payment_method.name
            valid_rows.append(row)

        if preview:
            total_deposits = sum(
                Decimal(r["amount"]) for r in valid_rows if r["type"] == "deposit"
            )
            total_withdrawals = sum(
                Decimal(r["amount"]) for r in valid_rows if r["type"] == "withdraw"
            )

            return Response(
                {
                    "preview": True,
                    "summary": {
                        "total_lines": len(lines),
                        "valid_lines": len(valid_rows),
                        "error_lines": len(error_rows),
                        "total_deposits": str(total_deposits),
                        "total_withdrawals": str(total_withdrawals),
                    },
                    "rows": valid_rows + error_rows,
                },
                status=status.HTTP_200_OK,
            )

        imported = []
        errors = []

        with db_transaction.atomic():
            for row in valid_rows:
                normalized_username = self.normalize_username(row["username"])

                # Check if same username exists in another casino
                existing_other_casino = Customer.objects.filter(
                    username__iexact=normalized_username
                ).exclude(casino_id=casino_id).first()

                if existing_other_casino:
                    errors.append(
                        {
                            **row,
                            "error": f"Username '{row['username']}' already exists in another casino.",
                        }
                    )
                    continue

                # Get existing customer in same casino, case-insensitive
                customer = Customer.objects.filter(
                    casino_id=casino_id,
                    username__iexact=normalized_username,
                ).order_by("id").first()

                created = False

                if not customer:
                    customer = Customer.objects.create(
                        username=normalized_username,
                        fullname=row["fullname"],
                        casino_id=casino_id,
                    )
                    created = True
                else:
                    # Optional: normalize old stored username if needed
                    if customer.username != normalized_username:
                        customer.username = normalized_username
                        customer.save(update_fields=["username"])

                tx = Transaction.objects.create(
                    customer=customer,
                    casino_id=casino_id,
                    added_by=request.user,
                    amount=Decimal(row["amount"]),
                    date=date_value,
                    notes=(notes_prefix or "").strip() or None,
                    type=row["type"],
                    platform_id=row["platform_id"],
                    payment_method_id=row["payment_method_id"],
                )

                imported.append(
                    {
                        "transaction_id": tx.id,
                        "customer_id": customer.id,
                        "username": customer.username,
                        "customer_created": created,
                        "type": tx.type,
                        "amount": str(tx.amount),
                        "platform": row["platform_name"],
                        "payment_method": row["payment_method_name"],
                    }
                )

        errors.extend(error_rows)

        return Response(
            {
                "preview": False,
                "summary": {
                    "total_lines": len(lines),
                    "imported_count": len(imported),
                    "error_count": len(errors),
                },
                "imported": imported,
                "errors": errors,
            },
            status=status.HTTP_200_OK,
        )

class ChatwootInboxListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        url = f"{settings.CHATWOOT_BASE_URL}/api/v1/accounts/{settings.CHATWOOT_ACCOUNT_ID}/inboxes"
        headers = {
            "api_access_token": settings.CHATWOOT_API_ACCESS_TOKEN,
            "Content-Type": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("payload", data if isinstance(data, list) else []):
            results.append({
                "id": str(item.get("id")),
                "name": item.get("name"),
                "channel_type": item.get("channel_type"),
            })

        return Response(results)
class ChatwootConnectInboxView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        casino_id = request.data.get("casino_id")
        inbox_id = str(request.data.get("inbox_id") or "")

        if not casino_id or not inbox_id:
            return Response({"detail": "casino_id and inbox_id are required"}, status=400)

        casino = Casino.objects.filter(id=casino_id).first()
        if not casino:
            return Response({"detail": "Casino not found"}, status=404)

        url = f"{settings.CHATWOOT_BASE_URL}/api/v1/accounts/{settings.CHATWOOT_ACCOUNT_ID}/inboxes/{inbox_id}"
        headers = {
            "api_access_token": settings.CHATWOOT_API_ACCESS_TOKEN,
            "Content-Type": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        inbox = response.json()

        casino.chatwoot_inbox_id = str(inbox.get("id"))
     
        casino.save(update_fields=["chatwoot_inbox_id"])

        return Response({
            "success": True,
            "message": "Inbox connected successfully",
            "casino_id": casino.id,
            "chatwoot_inbox_id": casino.chatwoot_inbox_id,
            "chatwoot_inbox_name": casino.name,
        })
class ChatwootWebhookView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    ACTION_TO_TRANSACTION_TYPE = {
        "rec": Transaction.TransactionType.DEPOSIT,
        "recv": Transaction.TransactionType.DEPOSIT,
        "received": Transaction.TransactionType.DEPOSIT,
        "in": Transaction.TransactionType.DEPOSIT,
        "dep": Transaction.TransactionType.DEPOSIT,
        "deposit": Transaction.TransactionType.DEPOSIT,
        "out": Transaction.TransactionType.WITHDRAW,
        "wd": Transaction.TransactionType.WITHDRAW,
        "withdraw": Transaction.TransactionType.WITHDRAW,
    }

    def post(self, request, *args, **kwargs):
        data = request.data

        print("\n=== CHATWOOT WEBHOOK RECEIVED ===")
        # print("Headers:")
        # print(json.dumps(dict(request.headers), indent=2))
        # print("Payload:")
        # print(json.dumps(data, indent=2))
        print("=================================\n")

        # Optional: verify Chatwoot signature
        if not self.is_valid_signature(request):
            return Response({"error": "Invalid signature"}, status=401)

        event_name = data.get("event")
        if event_name != "message_created":
            return Response({"status": "ignored", "reason": "not message_created"}, status=200)

        try:
            self.handle_event(data)
        except Exception as e:
            print("❌ ERROR PROCESSING CHATWOOT EVENT:", str(e))
            return Response({"status": "error", "detail": str(e)}, status=200)

        return Response({"status": "received"}, status=200)

    def is_valid_signature(self, request) -> bool:
        """
        Optional signature verification.
        Enable only if CHATWOOT_WEBHOOK_SECRET is set.
        """
        secret = getattr(settings, "CHATWOOT_WEBHOOK_SECRET", None)
        if not secret:
            return True

        signature = request.headers.get("X-Chatwoot-Signature", "")
        if not signature.startswith("sha256="):
            return False

        received_sig = signature.split("sha256=", 1)[1]
        raw_body = request.body or b""

        expected_sig = hmac.new(
            key=secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(received_sig, expected_sig)

    def handle_event(self, data: dict):
        content = (data.get("content") or "").strip()
        message_type = (data.get("message_type") or "").strip().lower()  # incoming / outgoing
        content_type = (data.get("content_type") or "").strip().lower()
        event_name = data.get("event")

        content_attributes = data.get("content_attributes") or {}
        external_echo = bool(content_attributes.get("external_echo", False))

        conversation = data.get("conversation") or {}
        inbox = data.get("inbox") or {}
        meta = conversation.get("meta") or {}
        sender_meta = meta.get("sender") or {}
        contact_inbox = conversation.get("contact_inbox") or {}

        print("event:", event_name)
        print("message_type:", message_type)
        print("content_type:", content_type)
        print("external_echo:", external_echo)
        print("content:", content)

        if content_type != "text":
            print("Ignoring non-text message")
            return

        if not content:
            print("Ignoring empty text")
            return
        if message_type == "outgoing":
            parsed = self.parse_transaction_message(content)
        else:
            parsed = ""
        if not parsed:
            print("Message pattern not matched")
            return

        # -----------------------------
        # Mapping Chatwoot -> old FB logic
        # -----------------------------
        #
        # We need:
        #   1. casino identifier (like old page_id)
        #   2. customer external id (like old fb_user_id)
        #
        # Recommended:
        #   - map casino using Chatwoot inbox id
        #   - map customer using contact_inbox.source_id if available
        #
        # Why?
        #   - inbox.id is stable per connected Chatwoot inbox
        #   - contact_inbox.source_id is the external source identifier for that contact
        #
        # If you want zero model changes, you can store this external contact id
        # in Customer.fb_user_id as a compatibility field.
        # -----------------------------

        inbox_id = str(inbox.get("id") or conversation.get("inbox_id") or "")
        customer_external_id = str(
            contact_inbox.get("source_id")
            or sender_meta.get("id")
            or ""
        )
        print(inbox_id)
        if not inbox_id:
            raise Exception("No Chatwoot inbox id found")

        if not customer_external_id:
            raise Exception("No Chatwoot customer external id found")

        is_echo = message_type == "outgoing" and external_echo

        self.create_customer_and_transaction(
            inbox_id=inbox_id,
            customer_external_id=customer_external_id,
            customer_name=sender_meta.get("name") or "",
            staff_code=parsed["staff_code"],
            payment_method_name=parsed["payment_method"],
            platform_name=parsed["platform"],
            amount=parsed["amount"],
            tx_type=parsed["tx_type"],
            raw_text=content,
            is_echo=is_echo,
        )

    def parse_transaction_message(self, text: str):
        """
        Supports 2 formats:

        1) With staff code:
           WA001 chime 100 gv recv

        2) Without staff code:
           chime 100 gv recv
        """
        parts = text.split()

        # Format 1: STAFFCODE PAYMENTMETHOD AMOUNT PLATFORM ACTION
        if len(parts) >= 5:
            possible_staff_code = parts[0].strip()
            amount_raw = parts[2].strip()
            action_raw = parts[-1].strip().lower()

            try:
                amount = Decimal(amount_raw)
                tx_type = self.ACTION_TO_TRANSACTION_TYPE.get(action_raw)
                if tx_type:
                    payment_method_name = parts[1].strip()
                    platform_name = " ".join(parts[3:-1]).strip()

                    if payment_method_name and platform_name:
                        return {
                            "staff_code": possible_staff_code,
                            "payment_method": payment_method_name,
                            "amount": amount,
                            "platform": platform_name,
                            "tx_type": tx_type,
                        }
            except (InvalidOperation, TypeError):
                pass

        # Format 2: PAYMENTMETHOD AMOUNT PLATFORM ACTION
        if len(parts) >= 4:
            amount_raw = parts[1].strip()
            action_raw = parts[-1].strip().lower()

            try:
                amount = Decimal(amount_raw)
                tx_type = self.ACTION_TO_TRANSACTION_TYPE.get(action_raw)
                if tx_type:
                    payment_method_name = parts[0].strip()
                    platform_name = " ".join(parts[2:-1]).strip()

                    if payment_method_name and platform_name:
                        return {
                            "staff_code": None,
                            "payment_method": payment_method_name,
                            "amount": amount,
                            "platform": platform_name,
                            "tx_type": tx_type,
                        }
            except (InvalidOperation, TypeError):
                pass

        return None

    def get_casino_by_chatwoot_inbox_id(self, inbox_id: str):
        """
        Best approach: add chatwoot_inbox_id to Casino model.
        """
        casino = Casino.objects.filter(
            chatwoot_inbox_id=str(inbox_id),
            is_active=True
        ).first()

        if not casino:
            raise Exception(f"No active casino found for chatwoot_inbox_id={inbox_id}")

        return casino

    def generate_unique_username(self, full_name: str) -> str:
        base = slugify(full_name).strip("-")
        if not base:
            base = "chatwoot-user"

        username = base
        counter = 1

        while Customer.objects.filter(username=username).exists():
            username = f"{base}-{counter}"
            counter += 1

        return username

    @db_transaction.atomic
    def create_customer_and_transaction(
        self,
        *,
        inbox_id: str,
        customer_external_id: str,
        customer_name: str,
        staff_code: str | None,
        payment_method_name: str,
        platform_name: str,
        amount: Decimal,
        tx_type: str,
        raw_text: str,
        is_echo: bool,
    ):
        casino = self.get_casino_by_chatwoot_inbox_id(inbox_id)

        payment_method = PaymentMethod.objects.filter(
            name__iexact=payment_method_name
        ).first()
        if not payment_method:
            raise Exception(f"Payment method '{payment_method_name}' not found")

        platform = Platforms.objects.filter(
            name__iexact=platform_name
        ).first()
        if not platform:
            raise Exception(f"Platform '{platform_name}' not found")

        # Reuse fb_user_id field for compatibility if you don't want schema change yet
        customer = Customer.objects.filter(
            fb_user_id=customer_external_id,
            casino=casino
        ).first()

        if not customer:
            full_name = (customer_name or "").strip() or f"chatwoot-user-{customer_external_id}"
            username = self.generate_unique_username(full_name)

            customer = Customer.objects.create(
                fullname=full_name,
                username=username,
                fb_user_id=customer_external_id,  # compatibility reuse
                casino=casino,
                notes="Created automatically from Chatwoot webhook",
            )
            print(f"Created customer: {customer.fullname} ({customer.username})")

        added_by = None
        if staff_code:
            added_by = User.objects.filter(
                staff_code__iexact=staff_code,
                casino=casino
            ).first()
            if not added_by:
                print(f"⚠ Staff with code '{staff_code}' not found in this casino, added_by will be null")

        note_prefix = "Chatwoot echo message" if is_echo else "Chatwoot incoming message"

        Transaction.objects.create(
            customer=customer,
            casino=casino,
            added_by=added_by,
            amount=amount,
            date=localdate(),
            notes=f"{note_prefix}: {raw_text}",
            type=tx_type,
            platform=platform,
            payment_method=payment_method,
        )

        if added_by:
            print(f"✅ Transaction created by staff: {added_by.staff_code}")
        else:
            print("✅ Transaction created with added_by = null")