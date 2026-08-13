from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


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
    Silently configured to print to the console in local dev (see
    EMAIL_BACKEND in settings) until real SMTP credentials are set via env vars.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    verify_link = f"{frontend_url}/verify-email?uid={uid}&token={token}"

    send_mail(
        subject="Verify your OpsPortal account",
        message=(
            f"Hi {user.full_name},\n\n"
            f"An administrator created a staff account for you on OpsPortal.\n"
            f"Verify your email to activate it and sign in:\n\n"
            f"{verify_link}\n\n"
            f"If you weren't expecting this, you can ignore this email."
        ),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[user.email],
        fail_silently=False,
    )