"""Reusable authorization helpers.

Authentication (who are you?) and authorization (what may you do?) are kept
separate: views declare the permission they need, and anything else is refused
on the server regardless of what the UI shows.

- Anonymous visitors are sent to the login page.
- Logged-in users who lack the permission get HTTP 403.
"""
from functools import wraps

from django.contrib.auth.mixins import PermissionRequiredMixin  # noqa: F401  (re-exported)
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def permission_required(*perms):
    """Function-view decorator: require ALL given permissions."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not request.user.has_perms(perms):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def get_employee_profile(user):
    """The Employee record linked to this login, or None."""
    if not user.is_authenticated:
        return None
    return getattr(user, "employee_profile", None)


def require_perm(user, perm):
    """Raise 403 unless the user holds `perm` (for checks inside a view)."""
    if not user.has_perm(perm):
        raise PermissionDenied
