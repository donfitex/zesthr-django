from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .services import accounts


class ForcePasswordChangeMiddleware:
    """Signed-in users flagged `must_change_password` can only change it or sign out."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and accounts.must_change_password(user):
            allowed = (reverse("password_change"), reverse("logout"))
            if request.path not in allowed and not request.path.startswith(settings.STATIC_URL):
                messages.warning(request, "Please choose a new password before continuing.")
                return redirect("password_change")
        return self.get_response(request)
