from django.urls import re_path
from .consumers import ConversationConsumer,ConversationListConsumer

websocket_urlpatterns = [
    re_path(r"ws/conversations/(?P<conversation_id>\d+)/$", ConversationConsumer.as_asgi()),
    re_path(
        r"ws/conversations/$",
        ConversationListConsumer.as_asgi(),
    ),
]