import logging

import requests
from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Stateless token generator — no extra DB table needed. Hashing in
    ``is_verified`` means a token stops working the moment the account gets
    verified (or a staffer's role/active-state changes), so old links in
    inboxes can't be replayed."""

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.password}{user.is_verified}{timestamp}"


email_verification_token = EmailVerificationTokenGenerator()


def send_verification_email(user, request=None):
    """Emails a one-time verification link to a newly-invited staff member.

    Django still generates the uid/token and owns verification (see
    verify_email in views.py) — only *delivery* is delegated. The link is
    POSTed to a Supabase Edge Function (send-verification-email), which
    sends the actual email via Resend. Requires SUPABASE_EDGE_FUNCTIONS_URL
    and SUPABASE_EDGE_FUNCTION_SECRET to be set as env vars (the secret must
    match the EDGE_FUNCTION_SECRET configured on the Supabase function).
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    verify_link = f"{frontend_url}/verify-email?uid={uid}&token={token}"

    functions_url = getattr(settings, 'SUPABASE_EDGE_FUNCTIONS_URL', '').rstrip('/')
    edge_secret = getattr(settings, 'SUPABASE_EDGE_FUNCTION_SECRET', '')

    if not functions_url or not edge_secret:
        logger.error(
            "Cannot send verification email to %s: SUPABASE_EDGE_FUNCTIONS_URL / "
            "SUPABASE_EDGE_FUNCTION_SECRET not configured.", user.email
        )
        user.verification_email_sent = False
        return False

    try:
        resp = requests.post(
            f"{functions_url}/send-verification-email",
            json={
                "email": user.email,
                "full_name": user.full_name,
                "verify_link": verify_link,
            },
            headers={
                "Content-Type": "application/json",
                "x-edge-secret": edge_secret,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error(
                "Supabase edge function failed to send verification email to %s: "
                "%s %s", user.email, resp.status_code, resp.text
            )
            user.verification_email_sent = False
            return False

        user.verification_email_sent = True
        return True
    except requests.RequestException as e:
        logger.error("Failed to reach Supabase edge function for %s: %s", user.email, e)
        user.verification_email_sent = False
        return False