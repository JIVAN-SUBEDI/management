from django.conf import settings
from django.utils.crypto import constant_time_compare
import hmac
import hashlib
from .firebase import send_fcm_to_tokens
from accounts.models import UserDevice


def get_allowed_inbox_ids(user):
    # ✅ SUPER ADMIN BYPASS
    if user.role == "super_admin":
        return None


    inbox_ids = (
        user.casinos
        .exclude(chatwoot_inbox_id__isnull=True)
        .values_list("chatwoot_inbox_id", flat=True)
        .distinct()
    )

    return [int(i) for i in inbox_ids if i is not None]

def user_can_access_conversation(user, conversation_payload: dict) -> bool:

    allowed_inbox_ids = get_allowed_inbox_ids(user)
    if allowed_inbox_ids is None:
        return True

    inbox_id = conversation_payload.get("inbox_id")
    return inbox_id in allowed_inbox_ids


def is_valid_signature(request):
    secret = getattr(settings, "CHATWOOT_WEBHOOK_SECRET_CHATS", None)

    if not secret:
        return True

    signature = (
        request.headers.get("X-Chatwoot-Signature")
        or request.META.get("HTTP_X_CHATWOOT_SIGNATURE")
    )

    if not signature or not signature.startswith("sha256="):
        return False

    received_sig = signature.split("sha256=", 1)[1]

    raw_body = request.body  # MUST be raw

    expected_sig = hmac.new(
        key=secret.encode(),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()



    return hmac.compare_digest(received_sig, expected_sig)
def build_reply_preview_from_message(message):
    if not message:
        return None

    sender = message.get("sender") or {}
    attachments = message.get("attachments") or []

    return {
        "id": message.get("id"),
        "content": message.get("content"),
        "text": message.get("content"),
        "sender_name": sender.get("name"),
        "message_type": message.get("message_type"),
        "attachments": attachments,
    }

def format_sender(sender):
    sender = sender or {}
    return {
        "id": sender.get("id"),
        "name": sender.get("name"),
        "email": sender.get("email"),
        "phone_number": sender.get("phone_number"),
        "thumbnail": sender.get("thumbnail"),
        "availability_status": sender.get("availability_status"),
    }


def format_message(message):
    return {
        "id": message.get("id"),
        "content": message.get("content"),
        "message_type": message.get("message_type"),
        "content_type": message.get("content_type"),
        "content_attributes": message.get("content_attributes") or {},
        "created_at": message.get("created_at"),
        "updated_at": message.get("updated_at"),
        "conversation_id": message.get("conversation_id"),
        "status": message.get("status"),
        "private": message.get("private", False),
        "source_id": message.get("source_id"),
        "attachments": message.get("attachments", []),
        "sender": format_sender(message.get("sender")),
    }


def format_conversation(conversation_data: dict, messages: list[dict]):
    meta = conversation_data.get("meta") or {}
    sender = meta.get("sender") or {}
    assignee = meta.get("assignee") or {}
    team = meta.get("team") or {}

    return {
        "id": conversation_data.get("id"),
        "uuid": conversation_data.get("uuid"),
        "status": conversation_data.get("status"),
        "priority": conversation_data.get("priority"),
        "inbox_id": conversation_data.get("inbox_id"),
        "can_reply": conversation_data.get("can_reply"),
        "unread_count": conversation_data.get("unread_count", 0),
        "labels": conversation_data.get("labels", []),
        "created_at": conversation_data.get("created_at"),
        "updated_at": conversation_data.get("updated_at"),
        "last_activity_at": conversation_data.get("last_activity_at"),
        "contact": {
            "id": sender.get("id"),
            "source_id":sender.get("source_id"),
            "name": sender.get("name"),
            "email": sender.get("email"),
            "phone_number": sender.get("phone_number"),
            "thumbnail": sender.get("thumbnail"),
            "identifier": sender.get("identifier"),
        },
        "assignee": {
            "id": assignee.get("id"),
            "name": assignee.get("name"),
            "email": assignee.get("email"),
            "thumbnail": assignee.get("thumbnail"),
        } if assignee else None,
        "team": {
            "id": team.get("id"),
            "name": team.get("name"),
        } if team else None,
        "custom_attributes": conversation_data.get("custom_attributes") or {},
        "additional_attributes": conversation_data.get("additional_attributes") or {},
        "messages": [format_message(m) for m in messages],
    }

def notify_all_devices(title, body, data=None):
    tokens = list(
        UserDevice.objects.filter(is_active=True)
        .values_list("fcm_token", flat=True)
    )

    return send_fcm_to_tokens(
        tokens=tokens,
        title=title,
        body=body,
        data=data,
    )