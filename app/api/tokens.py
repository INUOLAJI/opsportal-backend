import logging

import requests
from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


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

    Django generates the uid/token and owns verification (see verify_email
    in views.py). Delivery goes through Brevo's HTTP API (port 443) rather
    than SMTP, since Render's free tier blocks outbound SMTP ports
    (25/465/587) entirely — SMTP credentials, however correct, can never
    connect from there. Requires BREVO_API_KEY and BREVO_FROM_EMAIL to be
    set (see settings.py); BREVO_FROM_EMAIL must be an address verified
    under Brevo's "Add a Sender" flow.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    verify_link = f"{frontend_url}/verify-email?uid={uid}&token={token}"

    api_key = getattr(settings, 'BREVO_API_KEY', '')
    from_email = getattr(settings, 'BREVO_FROM_EMAIL', '')

    if not api_key or not from_email:
        logger.error(
            "Cannot send verification email to %s: BREVO_API_KEY / "
            "BREVO_FROM_EMAIL not configured.", user.email
        )
        user.verification_email_sent = False
        return False

    body_text = (
        f"Hi {user.full_name},\n\n"
        f"An admin has created a staff account for you on OpsPortal. "
        f"Confirm your email address to activate your account and sign in:\n\n"
        f"{verify_link}\n\n"
        f"If you weren't expecting this, you can ignore this email.\n"
    )

    payload = {
        "sender": {"name": "OpsPortal", "email": from_email},
        "to": [{"email": user.email, "name": user.full_name}],
        "subject": "Confirm your OpsPortal account",
        "textContent": body_text,
    }

    try:
        resp = requests.post(
            BREVO_SEND_URL,
            json=payload,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=10,
        )
        # Brevo returns 201 Created with a messageId on success.
        if resp.status_code >= 400:
            logger.error(
                "Brevo failed to send verification email to %s: %s %s",
                user.email, resp.status_code, resp.text
            )
            user.verification_email_sent = False
            return False

        print(f"[verify-email] Brevo accepted send for {user.email} (status {resp.status_code})")
        user.verification_email_sent = True
        return True
    except requests.RequestException:
        logger.exception("Failed to reach Brevo for %s", user.email)
        user.verification_email_sent = False
        return False