from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, TransactionViewSet,CampaignSegmentsView
from django.urls import path
router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customers")
router.register("transactions", TransactionViewSet, basename="transactions")

urlpatterns =[
    path("campaigns/segments/", CampaignSegmentsView.as_view(), name="campaign-segments"),
]+ router.urls