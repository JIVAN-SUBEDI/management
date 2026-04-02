from django.urls import path
from .views import CasinoAdminDashboardView,AnalyticsView,ReportsView,SuperAdminDashboardView

urlpatterns = [
    path("dashboard/casino-admin/", CasinoAdminDashboardView.as_view(), name="casino-admin-dashboard"),
    path("analytics/", AnalyticsView.as_view(), name="analytics"),
    path("reports/", ReportsView.as_view(), name="reports"),
    path("dashboard/super-admin/", SuperAdminDashboardView.as_view(), name="super-admin-dashboard"),
    
]