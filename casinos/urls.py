from rest_framework.routers import DefaultRouter
from .views import CasinoViewSet,PaymentMethodViewSet,PlatformsViewSet,DailyNoteParserView,ChatwootWebhookView,ChatwootInboxListView,ChatwootConnectInboxView
from django.urls import path
router = DefaultRouter()
router.register("casinos", CasinoViewSet, basename="casinos")
router.register("payment-methods",PaymentMethodViewSet, basename="payment-methods")
router.register("platforms",PlatformsViewSet, basename="platforms")
urlpatterns = [
    path("parser/daily-notes/", DailyNoteParserView.as_view(), name="daily-note-parser"),

    path("chatwoot/webhook/", ChatwootWebhookView.as_view(), name="chatwoot-webhook"),
    path("chatwoot/inboxes/", ChatwootInboxListView.as_view(), name="chatwoot-inboxes"),
    path("chatwoot/connect-inbox/", ChatwootConnectInboxView.as_view(), name="connect-inbox"),

]+router.urls