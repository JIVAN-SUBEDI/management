import requests
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication
from rest_framework import status
from django.conf import settings
from casinos.views import ChatwootWebhookView as webhookview
from .serializers import SendMessageSerializer, TypingSerializer, MessageListSerializer,MessageActionSerializer
from .utils import (
    user_can_access_conversation,
    format_conversation,
    format_message,
    build_reply_preview_from_message,is_valid_signature,notify_all_devices
)
from .services.chatwoot import ChatwootService
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from accounts.models import UserDevice
from .firebase import send_fcm_to_tokens
from casinos.models import Casino
class ChatwootConversationFullView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id: int):
        service = ChatwootService()

        try:
            # 1) get conversation meta/header/contact
            convo_resp = service.get_conversation(conversation_id)
            if convo_resp.status_code != 200:
                return Response(
                    {
                        "success": False,
                        "message": "Failed to fetch conversation",
                        "chatwoot_status": convo_resp.status_code,
                        "chatwoot_response": convo_resp.text,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            convo_data = convo_resp.json()

            # 2) permission check
            if not user_can_access_conversation(request.user, convo_data):
                return Response(
                    {
                        "success": False,
                        "message": "You do not have access to this conversation.",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            # 3) get full message thread from messages endpoint
            msg_resp = service.get_messages(conversation_id)
            if msg_resp.status_code != 200:
                return Response(
                    {
                        "success": False,
                        "message": "Failed to fetch messages",
                        "chatwoot_status": msg_resp.status_code,
                        "chatwoot_response": msg_resp.text,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            msg_data = msg_resp.json()
            messages = msg_data.get("payload", [])



            return Response(
                {
                    "success": True,
                    "conversation": format_conversation(convo_data, messages),
                    "messages_meta": msg_data.get("meta", {}),
                },
                status=status.HTTP_200_OK,
            )

        except requests.RequestException as e:
            return Response(
                {
                    "success": False,
                    "message": "Error connecting to Chatwoot",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

class ChatwootConversationMessagesView(APIView):
    permission_classes = [IsAuthenticated]
    # authentication_classes = [SessionAuthentication]

    def get(self, request, conversation_id: int):
        query = MessageListSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        service = ChatwootService()

        try:
            convo_resp = service.get_conversation(conversation_id)
            if convo_resp.status_code != 200:
                return Response(
                    {"success": False, "message": "Conversation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            convo_data = convo_resp.json()
            if not user_can_access_conversation(request.user, convo_data):
                return Response(
                    {"success": False, "message": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            before = query.validated_data.get("before")
            after = query.validated_data.get("after")

            resp = service.get_messages(
                conversation_id,
                before=before,
                after=after,
            )

            if resp.status_code != 200:
                return Response(
                    {
                        "success": False,
                        "message": "Failed to fetch messages",
                        "chatwoot_status": resp.status_code,
                        "chatwoot_response": resp.text,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            data = resp.json()
            payload = data.get("payload", [])

            return Response(
                {
                    "success": True,
                    "messages": [format_message(m) for m in payload],
                    "meta": data.get("meta", {}),
                },
                status=status.HTTP_200_OK,
            )

        except requests.RequestException as e:
            return Response(
                {
                    "success": False,
                    "message": "Error connecting to Chatwoot",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )


class ChatwootConversationSendMessageView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, conversation_id: int):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ChatwootService()
        channel_layer = get_channel_layer()

        try:
            convo_resp = service.get_conversation(conversation_id)
            if convo_resp.status_code != 200:
                return Response(
                    {"success": False, "message": "Conversation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            convo_data = convo_resp.json()

            if not user_can_access_conversation(request.user, convo_data):
                return Response(
                    {"success": False, "message": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            content = serializer.validated_data.get("content", "") or ""
            private = serializer.validated_data.get("private", False)
            attachments = request.FILES.getlist("attachments")

            if not content and not attachments:
                return Response(
                    {"success": False, "message": "Content or attachment is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            webhook_helper = webhookview()
            parsed_transaction = webhook_helper.parse_transaction_message(content)

            # Transaction command should never go to customer
            if parsed_transaction:
                private = True

            reply_to_message_id = serializer.validated_data.get("reply_to_message_id")

            content_attributes = {
                "sent_by_user_id": request.user.id,
                "sent_by_name": getattr(request.user, "full_name", None),
                "sent_by_type": getattr(request.user, "role", None),

                # trusted staff data from logged-in user
                "staff_id": request.user.id,
                "staff_code": getattr(request.user, "staff_code", None),
            }

            if parsed_transaction:
                content_attributes["is_transaction_message"] = True
                content_attributes["transaction_data"] = {
                    "staff_id": request.user.id,
                    "staff_code": getattr(request.user, "staff_code", None),
                    "payment_method": parsed_transaction.get("payment_method"),
                    "amount": str(parsed_transaction.get("amount")),
                    "platform": parsed_transaction.get("platform"),
                    "tx_type": parsed_transaction.get("tx_type"),
                }

            if reply_to_message_id:
                reply_resp = service.get_message(conversation_id, reply_to_message_id)

                if reply_resp.status_code != 200:
                    return Response(
                        {"success": False, "message": "Reply target message not found"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                reply_message = reply_resp.json()
                content_attributes["reply_to_message_id"] = reply_to_message_id
                content_attributes["replied_to"] = build_reply_preview_from_message(reply_message)

            resp = service.send_message(
                conversation_id=conversation_id,
                content=content,
                private=private,
                echo_id=serializer.validated_data.get("echo_id") or None,
                content_attributes=content_attributes,
                attachments=attachments,
            )

            if resp.status_code not in (200, 201):
                return Response(
                    {
                        "success": False,
                        "message": "Failed to send message",
                        "chatwoot_status": resp.status_code,
                        "chatwoot_response": resp.text,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            message_data = resp.json()
            formatted = format_message(message_data)

            if parsed_transaction:
                try:
                    inbox_id = str(
                        convo_data.get("inbox_id")
                        or (convo_data.get("inbox") or {}).get("id")
                        or ""
                    )

                    meta = convo_data.get("meta") or {}
                    sender_meta = meta.get("sender") or {}
                    contact_inbox = convo_data.get("contact_inbox") or {}

                    customer_external_id = str(
                        contact_inbox.get("source_id")
                        or sender_meta.get("id")
                        or ""
                    )

                    webhook_helper.create_customer_and_transaction(
                        inbox_id=inbox_id,
                        customer_external_id=customer_external_id,
                        customer_name=sender_meta.get("name") or "",
                        staff_user=request.user,
                        staff_code=getattr(request.user, "staff_code", None),
                        payment_method_name=parsed_transaction["payment_method"],
                        platform_name=parsed_transaction["platform"],
                        amount=parsed_transaction["amount"],
                        tx_type=parsed_transaction["tx_type"],
                        raw_text=content,
                        is_echo=True,
                    )

                except Exception as tx_error:
                    print("⚠ Transaction insert failed:", str(tx_error))

            # async_to_sync(channel_layer.group_send)(
            #     f"conversation_{conversation_id}",
            #     {
            #         "type": "conversation.message",
            #         "event": "message.sent",
            #         "conversation_id": conversation_id,
            #         "message": formatted,
            #     },
            # )

            return Response(
                {
                    "success": True,
                    "message": formatted,
                    "is_transaction": bool(parsed_transaction),
                    "forced_private": bool(parsed_transaction),
                },
                status=status.HTTP_200_OK,
            )

        except requests.RequestException as e:
            return Response(
                {
                    "success": False,
                    "message": "Error connecting to Chatwoot",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

class ChatwootConversationTypingView(APIView):
    permission_classes = [IsAuthenticated]
    # authentication_classes = [SessionAuthentication]

    def post(self, request, conversation_id: int):
        serializer = TypingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ChatwootService()
        channel_layer = get_channel_layer()

        try:
            convo_resp = service.get_conversation(conversation_id)
            if convo_resp.status_code != 200:
                return Response(
                    {"success": False, "message": "Conversation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            convo_data = convo_resp.json()
            if not user_can_access_conversation(request.user, convo_data):
                return Response(
                    {"success": False, "message": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            typing_status = serializer.validated_data["typing_status"]

            resp = service.toggle_typing(
                conversation_id=conversation_id,
                typing_status=typing_status,
            )

            if resp.status_code not in (200, 201):
                return Response(
                    {
                        "success": False,
                        "message": "Failed to toggle typing",
                        "chatwoot_status": resp.status_code,
                        "chatwoot_response": resp.text,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            async_to_sync(channel_layer.group_send)(
                f"conversation_{conversation_id}",
                {
                    "type": "conversation.typing",
                    "event": "typing",
                    "conversation_id": conversation_id,
                    "typing_status": typing_status,
                    "user": {
                        "id": request.user.id,
                        "name": getattr(request.user, "full_name", "") or getattr(request.user, "username", "User"),
                    },
                },
            )

            return Response(
                {
                    "success": True,
                    "typing_status": typing_status,
                },
                status=status.HTTP_200_OK,
            )

        except requests.RequestException as e:
            return Response(
                {
                    "success": False,
                    "message": "Error connecting to Chatwoot",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

class ChatwootConversationMessageActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int, message_id: int):
        serializer = MessageActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ChatwootService()
        channel_layer = get_channel_layer()

        try:
            convo_resp = service.get_conversation(conversation_id)
            if convo_resp.status_code != 200:
                return Response(
                    {"success": False, "message": "Conversation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            convo_data = convo_resp.json()

            if not user_can_access_conversation(request.user, convo_data):
                return Response(
                    {"success": False, "message": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            casino = ChatwootService.get_casino_for_conversation(request.user, convo_data)
            if not casino:
                return Response(
                    {
                        "success": False,
                        "message": "No casino/page found for this conversation inbox.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            page_id = getattr(casino, "fb_id", None)
            page_token = getattr(casino, "fb_access_token", None)

            if not page_id or not page_token:
                return Response(
                    {
                        "success": False,
                        "message": "Casino Facebook page id or page token missing.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # msg_resp = service.get_message(conversation_id, message_id)
            # if msg_resp.status_code != 200:
            #     return Response(
            #         {"success": False, "message": "Message not found"},
            #         status=status.HTTP_404_NOT_FOUND,
            #     )

            # message_data = msg_resp.json()
            # mid = message_data.get("source_id")

            # if not mid:
            #     return Response(
            #         {
            #             "success": False,
            #             "message": "This Chatwoot message has no Meta source_id / MID.",
            #         },
            #         status=status.HTTP_400_BAD_REQUEST,
            #     )

            psid = ChatwootService.get_psid_from_chatwoot_contact(service, convo_data, casino)

            if not psid:
                return Response(
                    {
                        "success": False,
                        "message": "Could not find PSID from Chatwoot contact_inboxes.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            action_type = serializer.validated_data["type"]

            if action_type == "reaction":
                reaction = serializer.validated_data.get("reaction")

                if not reaction:
                    return Response(
                        {"success": False, "message": "reaction is required."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                graph_resp = ChatwootService.send_meta_reaction(
                    page_id=page_id,
                    page_token=page_token,
                    psid=psid,
                    mid=message_id,
                    reaction=reaction,
                )

                if graph_resp.status_code not in (200, 201):
                    return Response(
                        {
                            "success": False,
                            "message": "Failed to send Meta reaction",
                            "graph_status": graph_resp.status_code,
                            "graph_response": graph_resp.text,
                            "psid": psid,
                            "mid": message_id,
                        },
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

                async_to_sync(channel_layer.group_send)(
                    f"conversation_{conversation_id}",
                    {
                        "type": "conversation.reaction",
                        "event": "reaction",
                        "conversation_id": conversation_id,
                        "message_id": str(message_id),
                        "reaction": reaction,
                        "user": {
                            "id": request.user.id,
                            "name": getattr(request.user, "full_name", "")
                            or getattr(request.user, "username", "User"),
                        },
                    },
                )

                return Response(
                    {
                        "success": True,
                        "type": "reaction",
                        "message_id": str(message_id),
                        "mid": message_id,
                        "psid": psid,
                        "reaction": reaction,
                        "graph_response": graph_resp.json(),
                    },
                    status=status.HTTP_200_OK,
                )

            if action_type == "reply":
                content = serializer.validated_data.get("content", "").strip()

                if not content:
                    return Response(
                        {"success": False, "message": "content is required for reply."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                graph_resp = ChatwootService.send_meta_reply(
                    page_id=page_id,
                    page_token=page_token,
                    psid=psid,
                    mid=message_id,
                    content=content,
                )

                if graph_resp.status_code not in (200, 201):
                    return Response(
                        {
                            "success": False,
                            "message": "Failed to send Meta reply",
                            "graph_status": graph_resp.status_code,
                            "graph_response": graph_resp.text,
                            "psid": psid,
                            "mid": message_id,
                        },
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

                return Response(
                    {
                        "success": True,
                        "type": "reply",
                        "message_id": str(message_id),
                        "mid": message_id,
                        "psid": psid,
                        "content": content,
                        "graph_response": graph_resp.json(),
                    },
                    status=status.HTTP_200_OK,
                )

        except requests.RequestException as e:
            return Response(
                {
                    "success": False,
                    "message": "Error connecting to Chatwoot or Meta Graph API",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
class ChatwootWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        raw_body = request.body

        if not is_valid_signature(request):
            return Response(
                {"success": False, "message": "Invalid webhook secret"},
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = request.data or {}
        event = payload.get("event")
        channel_layer = get_channel_layer()

        conversation = payload.get("conversation") or {}
        message = payload.get("message") or payload

        conversation_id = (
            conversation.get("id")
            or message.get("conversation_id")
            or payload.get("conversation_id")
        )

        if not conversation_id:
            return Response(
                {"success": True, "ignored": True, "reason": "No conversation id"},
                status=status.HTTP_200_OK,
            )

        room = f"conversation_{conversation_id}"

        def attachment_preview(attachments):
            if not attachments:
                return "New message"

            first = attachments[0] or {}
            file_type = str(first.get("file_type") or "").lower()

            if "image" in file_type:
                return "📷 Photo"
            if "video" in file_type:
                return "🎥 Video"
            if "audio" in file_type:
                return "🎵 Audio"

            return "📎 Attachment"

        def build_last_message(msg):
            attachments = msg.get("attachments") or []
            content = (msg.get("content") or "").strip()

            return {
                "id": msg.get("id"),
                "content": content or attachment_preview(attachments),
                "content_type": msg.get("content_type"),
                "message_type": msg.get("message_type"),
                "created_at": msg.get("created_at"),
                "status": msg.get("status"),
                "sender": msg.get("sender"),
                "attachments": attachments,
            }

        def build_list_conversation():
            last_message = build_last_message(message) if message else None

            contact = (
                conversation.get("contact")
                or conversation.get("meta", {}).get("sender")
                or payload.get("sender")
                or {}
            )

            return {
                "id": conversation_id,
                "status": conversation.get("status"),
                "priority": conversation.get("priority"),
                "inbox_id": conversation.get("inbox_id") or payload.get("inbox_id"),
                "can_reply": conversation.get("can_reply"),
                "unread_count": conversation.get("unread_count", 0),
                "labels": conversation.get("labels", []),
                "last_activity_at": (
                    conversation.get("last_activity_at")
                    or message.get("created_at")
                    or payload.get("created_at")
                ),
                "updated_at": (
                    conversation.get("updated_at")
                    or message.get("created_at")
                    or payload.get("updated_at")
                ),
                "contact": {
                    "id": contact.get("id"),
                    "name": contact.get("name") or "Customer",
                    "email": contact.get("email"),
                    "phone_number": contact.get("phone_number"),
                    "thumbnail": contact.get("thumbnail"),
                    "identifier": contact.get("identifier"),
                },
                "last_message": last_message,
            }

        def broadcast_to_list(event_name, formatted_message=None):
            inbox_id = (
                conversation.get("inbox_id")
                or payload.get("inbox_id")
                or message.get("inbox_id")
            )

            if not inbox_id:
                return

            async_to_sync(channel_layer.group_send)(
                f"conversations_list_inbox_{inbox_id}",
                {
                    "type": "conversation.list.update",
                    "event": event_name,
                    "conversation_id": conversation_id,
                    "conversation": build_list_conversation(),
                    "message": formatted_message or build_last_message(message),
                },
            )

        if event == "message_created":
            formatted_message = format_message(message) if message else build_last_message(payload)

            async_to_sync(channel_layer.group_send)(
                room,
                {
                    "type": "conversation.message",
                    "event": "message.created",
                    "conversation_id": conversation_id,
                    "message": formatted_message,
                    "conversation": {
                        "id": conversation.get("id") or conversation_id,
                        "status": conversation.get("status"),
                        "inbox_id": conversation.get("inbox_id") or payload.get("inbox_id"),
                        "last_activity_at": (
                            conversation.get("last_activity_at")
                            or message.get("created_at")
                            or payload.get("created_at")
                        ),
                    },
                },
            )

            broadcast_to_list("message.created", formatted_message)

            message_type = payload.get("message_type")
            is_incoming = message_type == 0 or message_type == "incoming"

            if is_incoming:
                inbox_id = (
                    payload.get("inbox_id")
                
                )

                sender_name = (
             
                    payload.get("sender", {}).get("name")
                    or "New message"
                )

                content = ( payload.get("content") or "").strip()
                attachments = payload.get("attachments") or []

                body = content or attachment_preview(attachments)

                tokens = list(
                    UserDevice.objects.filter(
                        is_active=True,
                        user__casinos__chatwoot_inbox_id=inbox_id,
                    )
                    .exclude(fcm_token__isnull=True)
                    .exclude(fcm_token="")
                    .values_list("fcm_token", flat=True)
                    .distinct()
                )

                send_fcm_to_tokens(
                    tokens=tokens,
                    title=sender_name,
                    body=body,
                    data={
                        "conversation_id": str(conversation_id),
                        "inbox_id": str(inbox_id),
                        "contact_name": str(sender_name),
                        "title": str(sender_name),
                        "body": str(body),
                        "type": "chat_message",
                    },
                )

        elif event == "message_updated":
            formatted_message = format_message(message) if message else build_last_message(payload)

            async_to_sync(channel_layer.group_send)(
                room,
                {
                    "type": "conversation.message",
                    "event": "message.updated",
                    "conversation_id": conversation_id,
                    "message": formatted_message,
                },
            )

            broadcast_to_list("message.updated", formatted_message)

        elif event in (
            "conversation_created",
            "conversation_updated",
            "conversation_status_changed",
        ):
            convo_payload = build_list_conversation()

            async_to_sync(channel_layer.group_send)(
                room,
                {
                    "type": "conversation.meta",
                    "event": event,
                    "conversation_id": conversation_id,
                    "conversation": convo_payload,
                },
            )

            broadcast_to_list(event)

        return Response({"success": True}, status=status.HTTP_200_OK)
class ChatwootConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    MAX_CHATWOOT_PAGES_TO_SCAN = 10

    def get_chatwoot_headers(self):
        return {
            "api_access_token": settings.CHATWOOT_API_ACCESS_TOKEN,
            "Content-Type": "application/json",
        }

    def get_allowed_inbox_ids(self, user):
        inbox_ids = (
            user.casinos
            .exclude(chatwoot_inbox_id__isnull=True)
            .values_list("chatwoot_inbox_id", flat=True)
            .distinct()
            .order_by("chatwoot_inbox_id")
        )
        return [int(i) for i in inbox_ids if i is not None]

    def get_target_inbox_ids(self, user, casino_id=None):
        if casino_id and str(casino_id) != "all":
            casino = Casino.objects.filter(id=casino_id).first()

            if not casino:
                return None, "Casino not found"

            if not casino.chatwoot_inbox_id:
                return None, "This casino has no Chatwoot inbox"

            if user.role != "super_admin":
                if not user.casinos.filter(id=casino.id).exists():
                    return None, "Access denied for this casino"

            return [int(casino.chatwoot_inbox_id)], None

        if user.role == "super_admin":
            return None, None

        return self.get_allowed_inbox_ids(user), None

    def format_message(self, message):
        if not message:
            return None

        sender = message.get("sender") or {}

        return {
            "id": message.get("id"),
            "content": message.get("content"),
            "content_type": message.get("content_type"),
            "message_type": message.get("message_type"),
            "created_at": message.get("created_at"),
            "status": message.get("status"),
            "sender": {
                "id": sender.get("id"),
                "name": sender.get("name"),
                "email": sender.get("email"),
                "phone_number": sender.get("phone_number"),
                "thumbnail": sender.get("thumbnail"),
            },
            "attachments": message.get("attachments", []),
        }

    def format_conversation(self, convo):
        meta = convo.get("meta") or {}
        sender = meta.get("sender") or {}
        assignee = meta.get("assignee") or {}
        team = meta.get("team") or {}
        last_message = convo.get("last_non_activity_message") or {}

        return {
            "id": convo.get("id"),
            "uuid": convo.get("uuid"),
            "inbox_id": convo.get("inbox_id"),
            "status": convo.get("status"),
            "priority": convo.get("priority"),
            "labels": convo.get("labels", []),
            "can_reply": convo.get("can_reply"),
            "unread_count": convo.get("unread_count", 0),
            "created_at": convo.get("created_at"),
            "updated_at": convo.get("updated_at"),
            "last_activity_at": convo.get("last_activity_at"),
            "timestamp": convo.get("timestamp"),
            "contact": {
                "id": sender.get("id"),
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
            "last_message": self.format_message(last_message),
            "custom_attributes": convo.get("custom_attributes", {}),
            "additional_attributes": convo.get("additional_attributes", {}),
        }

    def extract_payload_and_meta(self, response_json):
        if "data" in response_json:
            data = response_json.get("data") or {}
            return data.get("payload", []), data.get("meta", {})

        return response_json.get("payload", []), response_json.get("meta", {})

    def chatwoot_list_conversations(
        self,
        page,
        status_value=None,
        q=None,
        inbox_id=None,
    ):
        base_url = settings.CHATWOOT_BASE_URL.rstrip("/")
        account_id = settings.CHATWOOT_ACCOUNT_ID
        url = f"{base_url}/api/v1/accounts/{account_id}/conversations"

        params = {
            "page": page,
        }

        if status_value:
            params["status"] = status_value

        if q:
            params["q"] = q

        if inbox_id:
            params["inbox_id"] = int(inbox_id)

        return requests.get(
            url,
            headers=self.get_chatwoot_headers(),
            params=params,
            timeout=20,
        )

    def build_chatwoot_error_response(self, resp):
        return Response(
            {
                "success": False,
                "message": "Failed to fetch conversations from Chatwoot",
                "chatwoot_status": resp.status_code,
                "chatwoot_response": resp.text,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    def get(self, request, *args, **kwargs):
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            page_size = int(
                request.query_params.get("page_size", self.DEFAULT_PAGE_SIZE)
            )
            page_size = max(1, min(page_size, self.MAX_PAGE_SIZE))
        except ValueError:
            return Response(
                {"success": False, "message": "Invalid page or page_size"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        status_value = request.query_params.get("status")
        q = request.query_params.get("q")
        casino_id = request.query_params.get("casino_id")

        is_super_admin = request.user.role == "super_admin"

        try:
            target_inbox_ids, error = self.get_target_inbox_ids(
                request.user,
                casino_id=casino_id,
            )

            if error:
                return Response(
                    {"success": False, "message": error},
                    status=(
                        status.HTTP_403_FORBIDDEN
                        if error == "Access denied for this casino"
                        else status.HTTP_400_BAD_REQUEST
                    ),
                )

            # FAST PATH 1:
            # Super admin + All Pages = direct Chatwoot all conversations
            if is_super_admin and not casino_id:
                resp = self.chatwoot_list_conversations(
                    page=page,
                    status_value=status_value,
                    q=q,
                )

                if resp.status_code != 200:
                    return self.build_chatwoot_error_response(resp)

                payload, meta = self.extract_payload_and_meta(resp.json())

                return Response(
                    {
                        "success": True,
                        "source": "chatwoot_direct_all",
                        "page": page,
                        "page_size": page_size,
                        "filters": {
                            "status": status_value,
                            "q": q,
                            "casino_id": casino_id,
                            "inbox_ids": None,
                        },
                        "meta": meta,
                        "count": len(payload[:page_size]),
                        "results": [
                            self.format_conversation(c)
                            for c in payload[:page_size]
                        ],
                    },
                    status=status.HTTP_200_OK,
                )

            # FAST PATH 2:
            # Selected single casino/page = direct Chatwoot inbox_id filter
            if target_inbox_ids and len(target_inbox_ids) == 1:
                inbox_id = target_inbox_ids[0]

                resp = self.chatwoot_list_conversations(
                    page=page,
                    status_value=status_value,
                    q=q,
                    inbox_id=inbox_id,
                )

                if resp.status_code != 200:
                    return self.build_chatwoot_error_response(resp)

                payload, meta = self.extract_payload_and_meta(resp.json())

                return Response(
                    {
                        "success": True,
                        "source": "chatwoot_direct_inbox",
                        "page": page,
                        "page_size": page_size,
                        "filters": {
                            "status": status_value,
                            "q": q,
                            "casino_id": casino_id,
                            "inbox_ids": [inbox_id],
                        },
                        "meta": meta,
                        "count": len(payload[:page_size]),
                        "results": [
                            self.format_conversation(c)
                            for c in payload[:page_size]
                        ],
                    },
                    status=status.HTTP_200_OK,
                )

            # FALLBACK:
            # Staff with multiple allowed inboxes = scan + filter
            allowed_inbox_ids = set(target_inbox_ids or [])

            if not allowed_inbox_ids:
                return Response(
                    {
                        "success": True,
                        "source": "django_filtered_scan",
                        "page": page,
                        "page_size": page_size,
                        "filters": {
                            "status": status_value,
                            "q": q,
                            "casino_id": casino_id,
                            "inbox_ids": [],
                        },
                        "meta": {
                            "has_next": False,
                            "scanned_chatwoot_pages": 0,
                            "approx_total_filtered": 0,
                            "scan_capped": False,
                        },
                        "count": 0,
                        "results": [],
                    },
                    status=status.HTTP_200_OK,
                )

            needed = page * page_size
            collected = []
            scanned_pages = 0
            chatwoot_page = 1
            has_more_upstream = True
            seen_ids = set()

            while (
                has_more_upstream
                and len(collected) < needed
                and scanned_pages < self.MAX_CHATWOOT_PAGES_TO_SCAN
            ):
                resp = self.chatwoot_list_conversations(
                    page=chatwoot_page,
                    status_value=status_value,
                    q=q,
                )

                if resp.status_code != 200:
                    return self.build_chatwoot_error_response(resp)

                payload, meta = self.extract_payload_and_meta(resp.json())
                scanned_pages += 1

                if not payload:
                    has_more_upstream = False
                    break

                for convo in payload:
                    convo_id = convo.get("id")
                    inbox_id = convo.get("inbox_id")

                    try:
                        inbox_id = int(inbox_id) if inbox_id is not None else None
                    except (TypeError, ValueError):
                        inbox_id = None

                    if inbox_id in allowed_inbox_ids and convo_id not in seen_ids:
                        seen_ids.add(convo_id)
                        collected.append(convo)

                chatwoot_page += 1

            start = (page - 1) * page_size
            end = start + page_size
            paged_results = collected[start:end]
            has_next = len(collected) > end or has_more_upstream

            return Response(
                {
                    "success": True,
                    "source": "django_filtered_scan",
                    "page": page,
                    "page_size": page_size,
                    "filters": {
                        "status": status_value,
                        "q": q,
                        "casino_id": casino_id,
                        "inbox_ids": list(allowed_inbox_ids),
                    },
                    "meta": {
                        "has_next": has_next,
                        "scanned_chatwoot_pages": scanned_pages,
                        "approx_total_filtered": len(collected),
                        "scan_capped": (
                            scanned_pages >= self.MAX_CHATWOOT_PAGES_TO_SCAN
                            and has_more_upstream
                        ),
                    },
                    "count": len(paged_results),
                    "results": [
                        self.format_conversation(c)
                        for c in paged_results
                    ],
                },
                status=status.HTTP_200_OK,
            )

        except requests.RequestException as e:
            return Response(
                {
                    "success": False,
                    "message": "Error connecting to Chatwoot",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

class ChatwootConversationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: int):
        service = ChatwootService()

        try:
            convo_resp = service.get_conversation(conversation_id)

            if convo_resp.status_code != 200:
                return Response(
                    {"success": False, "message": "Conversation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            convo_data = convo_resp.json()

            if not user_can_access_conversation(request.user, convo_data):
                return Response(
                    {"success": False, "message": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            resp = service.mark_conversation_read(conversation_id)

            if resp.status_code not in (200, 201, 204):
                return Response(
                    {
                        "success": False,
                        "message": "Failed to update Chatwoot read status",
                        "chatwoot_status": resp.status_code,
                        "chatwoot_response": resp.text,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            return Response(
                {
                    "success": True,
                    "message": "Chatwoot conversation marked as read",
                },
                status=status.HTTP_200_OK,
            )

        except requests.RequestException as e:
            return Response(
                {
                    "success": False,
                    "message": "Error connecting to Chatwoot",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )