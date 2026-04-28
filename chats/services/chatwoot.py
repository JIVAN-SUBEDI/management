import requests
from django.conf import settings
from casinos.models import Casino
import json
class ChatwootService:
    def __init__(self):
        self.base_url = settings.CHATWOOT_BASE_URL.rstrip("/")
        self.account_id = settings.CHATWOOT_ACCOUNT_ID
        self.api_token = settings.CHATWOOT_API_ACCESS_TOKEN
        self.timeout = 20

    @property
    def headers(self):
        return {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
        }

    def build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_conversation(self, conversation_id: int):
        url = self.build_url(
            f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}"
        )
        return requests.get(url, headers=self.headers, timeout=self.timeout)

    def get_messages(
        self,
        conversation_id: int,
        *,
        before: int | None = None,
        after: int | None = None,
    ):
        url = self.build_url(
            f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"
        )

        params = {}
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after

        return requests.get(
            url,
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )
    def get_message(self, conversation_id: int, message_id: int):
        resp = self.get_messages(conversation_id)
        if resp.status_code != 200:
            return resp

        data = resp.json()
        payload = data.get("payload", [])
        found = None

        for item in payload:
            if str(item.get("source_id") or "") == str(message_id):
                found = item
                break

        class DummyResponse:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._data = data
                self.text = "" if data is None else str(data)

            def json(self):
                return self._data

        if not found:
            return DummyResponse(404, {"message": "Message not found"})

        return DummyResponse(200, found)
    def send_message(
        self,
        conversation_id,
        content="",
        private=False,
        echo_id=None,
        content_attributes=None,
        attachments=None,
    ):
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"

        # always ensure dict
        content_attributes = content_attributes or {}

        # 👇 THIS IS THE FIX
        if echo_id:
            content_attributes["echo_id"] = echo_id

        data = {
            "content": content,
            "message_type": "outgoing",
            "private": str(private).lower(),
            "content_attributes": json.dumps(content_attributes),  # must be JSON string
        }

        files = []

        if attachments:
            for file in attachments:
                files.append(
                    (
                        "attachments[]",
                        (
                            file.name,
                            file.read(),
                            file.content_type or "application/octet-stream",
                        ),
                    )
                )

        return requests.post(
            url,
            headers={
                "api_access_token": self.api_token,
            },
            data=data,
            files=files if files else None,
            timeout=30,
        )
    def toggle_typing(self, conversation_id: int, *, typing_status: str):
        url = self.build_url(
            f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/toggle_typing_status"
        )

        payload = {
            "typing_status": typing_status,
        }

        return requests.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )

    def list_webhooks(self):
        url = self.build_url(
            f"/api/v1/accounts/{self.account_id}/webhooks"
        )
        return requests.get(url, headers=self.headers, timeout=self.timeout)

    def create_webhook(self, *, url_value: str, name: str, subscriptions: list[str]):
        url = self.build_url(
            f"/api/v1/accounts/{self.account_id}/webhooks"
        )
        payload = {
            "url": url_value,
            "name": name,
            "subscriptions": subscriptions,
        }
        return requests.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )

    def update_webhook(
        self,
        webhook_id: int,
        *,
        url_value: str,
        name: str,
        subscriptions: list[str],
    ):
        url = self.build_url(
            f"/api/v1/accounts/{self.account_id}/webhooks/{webhook_id}"
        )
        payload = {
            "url": url_value,
            "name": name,
            "subscriptions": subscriptions,
        }
        return requests.patch(
            url,
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )
    def get_casino_for_conversation(user, convo_data):
        inbox_id = convo_data.get("inbox_id")

        if not inbox_id:
            return None

        if getattr(user, "role", None) == "super_admin":
            
            return Casino.objects.filter(chatwoot_inbox_id=inbox_id).first()

        return user.casinos.filter(chatwoot_inbox_id=inbox_id).first()
    def get_contact(self, contact_id):
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/contacts/{contact_id}"

        return requests.get(
            url,
            headers=self.headers,
            timeout=20,
        )
    def get_psid_from_chatwoot_contact(self, convo_data,casino):
        contact = convo_data.get("meta", {}).get("sender") or {}
        contact_id = contact.get("id")

        if not contact_id:
            return None

        contact_resp =self.get_contact(contact_id)
        if contact_resp.status_code != 200:
            return None

        contact_data = contact_resp.json()
        contact_inboxes = contact_data.get("payload", {}).get("contact_inboxes", [])

        for item in contact_inboxes:
            inbox = item.get("inbox") or {}
            if str(inbox.get("id")) == str(convo_data.get("inbox_id")):
                return item.get("source_id")

        for item in contact_inboxes:
            if item.get("source_id"):
                return item.get("source_id")

        return None
    def send_meta_reply(page_id, page_token, psid, mid, content):
        url = f"https://graph.facebook.com/v25.0/{page_id}/messages"

        return requests.post(
            url,
            params={"access_token": page_token},
            json={
                "messaging_type": "RESPONSE",
                "recipient": {"id": psid},
                "message": {"text": content},
                "reply_to": {"mid": mid},
            },
            timeout=20,
        )
    def send_meta_reaction(page_id: str, page_token: str, psid: str, mid: str, reaction: str):
        url = f"https://graph.facebook.com/v25.0/{page_id}/messages"

        return requests.post(
            url,
            params={"access_token": page_token},
            json={
                "recipient": {"id": psid},
                "sender_action": "react",
                "payload": {
                    "message_id": mid,   # MUST be Chatwoot message.source_id (m_xxx)
                    "reaction": reaction
                },
            },
            timeout=20,
        )
    def mark_conversation_read(self, conversation_id: int):
        url = self.build_url(
            f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/update_last_seen"
        )

        return requests.post(
            url,
            headers=self.headers,
            timeout=self.timeout,
        )