import logging

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
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

    Django generates the uid/token and owns verification (see verify_email
    in views.py), and also sends the email itself via Gmail SMTP using
    EMAIL_HOST_USER / EMAIL_HOST_PASSWORD (a Gmail App Password). No
    third-party domain verification required.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    verify_link = f"{frontend_url}/verify-email?uid={uid}&token={token}"

    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        logger.error(
            "Cannot send verification email to %s: EMAIL_HOST_USER / "
            "EMAIL_HOST_PASSWORD not configured.", user.email
        )
        user.verification_email_sent = False
        return False

    subject = "Confirm your OpsPortal account"
    message = (
        f"Hi {user.full_name},\n\n"
        f"An admin has created a staff account for you on OpsPortal. "
        f"Confirm your email address to activate your account and sign in:\n\n"
        f"{verify_link}\n\n"
        f"If you weren't expecting this, you can ignore this email.\n"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        user.verification_email_sent = True
        return True
    except Exception as e:
        logger.error("Failed to send verification email to %s: %s", user.email, e)
        user.verification_email_sent = False
        return False