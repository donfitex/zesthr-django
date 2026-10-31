from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import transaction, IntegrityError

from core.models import NeonIdentity
from core.services import neon_auth


class NeonBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not neon_auth.enabled() or not request or not username or not password:
            return None
        try:
            _, cookie = neon_auth.call('sign-in/email', payload={'email': username, 'password': password})
            if not cookie:
                raise neon_auth.NeonAuthError('No authentication session was returned.')
            profile = neon_auth.session_user(cookie)
            user = provision(profile)
            if not self.user_can_authenticate(user):
                return None
            request.session['neon_cookie'] = cookie
            request.session['neon_subject'] = str(profile['id'])
            return user
        except neon_auth.NeonAuthError:
            return None


@transaction.atomic
def provision(profile):
    """Never match an existing privileged/local account using its email address."""
    from django.conf import settings
    import hashlib
    issuer, subject = settings.NEON_AUTH_BASE_URL.rstrip('/'), str(profile['id'])
    identity = NeonIdentity.objects.select_related('user').filter(issuer=issuer, subject=subject).first()
    if identity:
        identity.user.email = str(profile.get('email', ''))[:254]
        identity.user.save(update_fields=['email'])
        return identity.user
    # Unique provider identity is the account key; email alone never grants access.
    username = 'neon_' + hashlib.sha256((issuer + ':' + subject).encode()).hexdigest()[:40]
    user = get_user_model()(username=username, email=str(profile.get('email', ''))[:254],
                           first_name=str(profile.get('name', ''))[:150])
    user.set_unusable_password()
    try:
        with transaction.atomic():
            user.save()
            NeonIdentity.objects.create(user=user, issuer=issuer, subject=subject)
        return user
    except IntegrityError:
        # A concurrent login may have provisioned the same verified identity.
        identity = NeonIdentity.objects.select_related('user').filter(issuer=issuer, subject=subject).first()
        if identity:
            return identity.user
        # A colliding local username is never adopted by email or by username.
        raise neon_auth.NeonAuthError('Account provisioning requires administrator assistance.') from None
