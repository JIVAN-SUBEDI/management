from django.contrib import admin
from django.urls import path, include,re_path
from accounts.views import index
from django.views.generic import TemplateView
urlpatterns = [
    path("admin/", admin.site.urls),
    path('', index, name='index'),
    path("api/accounts/", include("accounts.urls")),
    path("api/", include("casinos.urls")),
    path("api/", include("customer.urls")),
    path("api/", include("analytics.urls")),
    re_path(r"^(?!api/|admin/|static/).*$", TemplateView.as_view(template_name="index.html"))
]