from django.urls import path
from .views import (
    ChatwootConversationFullView,
    ChatwootConversationMessagesView,
    ChatwootConversationSendMessageView,
    ChatwootConversationTypingView,
    ChatwootWebhookView,
    ChatwootConversationListView,
    ChatwootConversationMessageActionView,
    ChatwootConversationMarkReadView
    # ListAllConversaitonsMessenger
)

urlpatterns = [
    path("chatwoot/conversations/", ChatwootConversationListView.as_view(), name="chatwoot-conversations"),
    path("chatwoot/conversations/<int:conversation_id>/", ChatwootConversationFullView.as_view()),
    path("chatwoot/conversations/<int:conversation_id>/messages/<str:message_id>/action/",ChatwootConversationMessageActionView.as_view(),),
    path("chatwoot/conversations/<int:conversation_id>/messages/", ChatwootConversationMessagesView.as_view()),
    path("chatwoot/conversations/<int:conversation_id>/send/", ChatwootConversationSendMessageView.as_view()),
    path("chatwoot/conversations/<int:conversation_id>/typing/", ChatwootConversationTypingView.as_view()),
    path("chatwoot/webhook/chats/", ChatwootWebhookView.as_view()),
    path(
    "chatwoot/conversations/<int:conversation_id>/read/",
    ChatwootConversationMarkReadView.as_view(),
),
    # path("messenger/conversations/",ListAllConversaitonsMessenger.as_view())
]