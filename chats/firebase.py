# notifications/firebase.py

import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
import os

def init_firebase():
    if not firebase_admin._apps:
        cred_path = os.path.join(settings.BASE_DIR, "backend", "firebase.json")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)


def send_fcm_to_tokens(tokens, title, body, data=None):
    init_firebase()

    tokens = [t for t in tokens if t]
    if not tokens:
        return {"success": False, "message": "No tokens"}

    data = {str(k): str(v) for k, v in (data or {}).items()}

    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                sound="default",
                channel_id="default",
            ),
        ),
    )

    response = messaging.send_each_for_multicast(message)

    return {
        "success": True,
        "success_count": response.success_count,
        "failure_count": response.failure_count,
        "responses": [
            {
                "success": r.success,
                "error": str(r.exception) if r.exception else None,
            }
            for r in response.responses
        ],
    }