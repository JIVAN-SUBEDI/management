from rest_framework.permissions import BasePermission,SAFE_METHODS


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == "super_admin"
        )


class IsSuperAdminOrCasinoAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ["super_admin", "casino_admin"]
        )

class IsAuthenticatedReadOnlySuperAdminWrite(BasePermission):


    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # GET, HEAD, OPTIONS
        if request.method in SAFE_METHODS:
            return True

        return request.user.role == "super_admin"