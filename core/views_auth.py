"""Sign-in, password change and password reset."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth
from django.urls import reverse_lazy
from django.views.generic.edit import FormView

from .forms_auth import PublicSignupForm
from . import roles
from .models import SecurityEvent
from .services import accounts


class LoginView(auth.LoginView):
    template_name = "login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "").strip()
        if accounts.is_login_blocked(username, accounts.client_ip(request)):
            accounts.record_event(SecurityEvent.LOGIN_BLOCKED, request=request, username=username)
            form = self.get_form()
            form.is_bound = True
            form.add_error(None, f"Too many failed attempts. Please wait {settings.LOGIN_FAILURE_WINDOW_MINUTES} "
                                 "minutes, or use \"Forgot password\".")
            response = self.render_to_response(self.get_context_data(form=form))
            response.status_code = 429
            return response
        return super().post(request, *args, **kwargs)

    def get_default_redirect_url(self):
        # Staff and employees land on their dashboard; accounts without one (e.g. a system
        # administrator) land on the home page instead of an "access denied" page.
        user = self.request.user
        if user.has_perm(roles.VIEW_ALL_ATTENDANCE) or getattr(user, "employee_profile", None):
            return super().get_default_redirect_url()
        return str(reverse_lazy("home"))

   
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        context["google_login_enabled"] = bool(
            settings.GOOGLE_OAUTH_CLIENT_ID
            and settings.GOOGLE_OAUTH_CLIENT_SECRET
        )

        return context

class PasswordChangeView(auth.PasswordChangeView):
    template_name = "password_change.html"
    success_url = reverse_lazy("home")

    def get_context_data(self, **kwargs):
        return super().get_context_data(forced=accounts.must_change_password(self.request.user), **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)  # also keeps THIS session signed in
        accounts.mark_password_changed(self.request.user)
        accounts.record_event(SecurityEvent.PASSWORD_CHANGED, request=self.request, user=self.request.user)
        messages.success(self.request, "Your password has been changed. Other devices were signed out.")
        return response


class PasswordResetView(auth.PasswordResetView):
    template_name = "password_reset_form.html"
    email_template_name = "password_reset_email.txt"
    subject_template_name = "password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        accounts.record_event(SecurityEvent.PASSWORD_RESET_REQUESTED, request=self.request,
                              username=form.cleaned_data["email"])
        return super().form_valid(form)  # always says "if that address exists..." (no account enumeration)


class PasswordResetConfirmView(auth.PasswordResetConfirmView):
    template_name = "password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        accounts.mark_password_changed(self.user)
        accounts.record_event(SecurityEvent.PASSWORD_RESET_COMPLETED, request=self.request, user=self.user)
        return response

class SignupView(FormView):
    template_name = "signup.html"
    form_class = PublicSignupForm
    success_url = reverse_lazy("login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["google_login_enabled"] = bool(
            settings.GOOGLE_OAUTH_CLIENT_ID
            and settings.GOOGLE_OAUTH_CLIENT_SECRET
        )

        return context

    def form_valid(self, form):
        form.save()

        messages.success(
            self.request,
            (
                "Your HROS account has been created successfully. "
                "You can now sign in. HR authorization is required "
                "before you can access employee, attendance, or payroll information."
            ),
        )

        return super().form_valid(form)