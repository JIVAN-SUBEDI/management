import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from casinos.models import Casino


@database_sync_to_async
def get_allowed_inbox_ids(user):
    if user.role == "super_admin":
        return list(
            Casino.objects
            .exclude(chatwoot_inbox_id__isnull=True)
            .exclude(chatwoot_inbox_id="")
            .values_list("chatwoot_inbox_id", flat=True)
            .distinct()
        )

    return list(
        user.casinos
        .exclude(chatwoot_inbox_id__isnull=True)
        .exclude(chatwoot_inbox_id="")
        .values_list("chatwoot_inbox_id", flat=True)
        .distinct()
    )


class ConversationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.room_group_name = f"conversation_{self.conversation_id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

    async def conversation_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "message",
            "event": event.get("event"),
            "conversation_id": event.get("conversation_id"),
            "message": event.get("message"),
            "conversation": event.get("conversation"),
        }))

    async def conversation_meta(self, event):
        await self.send(text_data=json.dumps({
            "type": "meta",
            "event": event.get("event"),
            "conversation_id": event.get("conversation_id"),
            "conversation": event.get("conversation"),
        }))

    async def conversation_reaction(self, event):
        await self.send(text_data=json.dumps({
            "type": "reaction",
            "event": event.get("event"),
            "conversation_id": event.get("conversation_id"),
            "message_id": event.get("message_id"),
            "reaction": event.get("reaction"),
            "user": event.get("user"),
        }))
    async def conversation_typing(self, event):
        await self.send(text_data=json.dumps({
            "type": "typing",
            "conversation_id": event.get("conversation_id"),
            "typing_status": event.get("typing_status"),
            "user": event.get("user"),
        }))



class ConversationListConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")

        if not user or user.is_anonymous:
            await self.close()
            return

        self.room_group_names = []

        inbox_ids = await get_allowed_inbox_ids(user)

        for inbox_id in inbox_ids:
            group_name = f"conversations_list_inbox_{inbox_id}"
            self.room_group_names.append(group_name)

            await self.channel_layer.group_add(
                group_name,
                self.channel_name,
            )

        await self.accept()

    async def disconnect(self, close_code):
        for group_name in getattr(self, "room_group_names", []):
            await self.channel_layer.group_discard(
                group_name,
                self.channel_name,
            )

    async def conversation_list_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "conversation_update",
            "event": event.get("event"),
            "conversation_id": event.get("conversation_id"),
            "conversation": event.get("conversation"),
            "message": event.get("message"),
        }))