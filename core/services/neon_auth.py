"""Server-side Better Auth REST client. Provider cookies stay in DB-backed sessions."""
from urllib.parse import urlsplit
from django.views.decorators.debug import sensitive_variables

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class NeonAuthError(Exception):
    pass


def enabled():
    return bool(settings.NEON_AUTH_BASE_URL)


@sensitive_variables('payload', 'cookie', 'headers', 'response', 'data', 'cookies')
def call(endpoint, *, payload=None, cookie=None, method='POST'):
    base = settings.NEON_AUTH_BASE_URL.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise ImproperlyConfigured('NEON_AUTH_BASE_URL must be an HTTPS auth endpoint URL.')
    headers = {'Accept': 'application/json', 'Origin': settings.NEON_AUTH_APP_ORIGIN}
    if cookie:
        headers['Cookie'] = cookie
    try:
        response = requests.request(method, base + '/' + endpoint, json=payload,
            headers=headers, timeout=10, allow_redirects=False)
        if response.status_code >= 300:
            raise NeonAuthError('Authentication could not be completed. Check your details or try again later.')
        data = response.json()
        if not isinstance(data, dict):
            raise NeonAuthError('Authentication session is unavailable.')
        cookies = '; '.join(f'{c.name}={c.value}' for c in response.cookies
                           if 'session_token' in c.name)
        return data, cookies
    except (requests.RequestException, ValueError) as exc:
        raise NeonAuthError('Authentication service is temporarily unavailable.') from exc


def session_user(cookie):
    data, _ = call('get-session', cookie=cookie, method='GET')
    user = data.get('user')
    if not isinstance(user, dict) or not data.get('session') or not user.get('id') or not user.get('emailVerified'):
        raise NeonAuthError('Verify your email before signing in, or sign in again.')
    return user
