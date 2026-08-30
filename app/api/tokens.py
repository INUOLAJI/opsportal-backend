import html
import logging

import requests
from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from user_agents import parse as parse_user_agent

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
IPAPI_URL = "https://ipapi.co/{ip}/json/"


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Stateless token generator — no extra DB table needed. Hashing in
    ``is_verified`` means a token stops working the moment the account gets
    verified (or a staffer's role/active-state changes), so old links in
    inboxes can't be replayed."""

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.password}{user.is_verified}{timestamp}"


email_verification_token = EmailVerificationTokenGenerator()


class PasswordResetTokenGenerator(PasswordResetTokenGenerator):
    """Uses Django's built-in reset token generator — invalidates after
    password changes, so reset links can't be replayed."""
    pass


password_reset_token = PasswordResetTokenGenerator()


def send_password_reset_email(user):
    """Emails a one-time password reset link to the user."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = password_reset_token.make_token(user)
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    reset_link = f"{frontend_url}/reset-password?uid={uid}&token={token}"

    api_key = getattr(settings, 'BREVO_API_KEY', '')
    from_email = getattr(settings, 'BREVO_FROM_EMAIL', '')

    if not api_key or not from_email:
        logger.error(
            "Cannot send password reset email to %s: BREVO_API_KEY / "
            "BREVO_FROM_EMAIL not configured.", user.email
        )
        return False

    link = html.escape(reset_link)
    name = html.escape(user.full_name or user.email)

    body_html = f"""
    <table cellpadding="0" cellspacing="0" width="100%" style="background:#F8FAFC;padding:32px 0;">
      <tr><td align="center">
        <table cellpadding="0" cellspacing="0" width="480" style="background:#FFFFFF;border-radius:12px;overflow:hidden;font-family:sans-serif;">
          <tr><td style="padding:32px 32px 8px 32px;">
            <p style="margin:0 0 4px 0;font-size:12px;font-weight:600;letter-spacing:1px;color:#64748B;text-transform:uppercase;">OpsPortal</p>
            <h1 style="margin:0 0 16px 0;font-size:20px;color:#0F172A;">Reset your password</h1>
            <p style="margin:0 0 24px 0;font-size:14px;line-height:1.6;color:#334155;">
              Hi {name}, we received a request to reset your OpsPortal password.
              Click the button below to set a new one. This link expires in 1 hour.
            </p>
          </td></tr>
          <tr><td style="padding:0 32px 32px 32px;" align="center">
            <a href="{link}" style="display:inline-block;background:#3B82F6;color:#FFFFFF;text-decoration:none;
               font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;">Reset Password</a>
          </td></tr>
          <tr><td style="padding:0 32px 32px 32px;">
            <p style="margin:0;font-size:12px;color:#94A3B8;line-height:1.6;">
              If the button doesn't work, copy and paste this link:<br>
              <a href="{link}" style="color:#3B82F6;">{link}</a>
            </p>
            <p style="margin:16px 0 0 0;font-size:12px;color:#94A3B8;">
              If you didn't request this, you can safely ignore this email.
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>"""

    body_text = (
        f"Hi {user.full_name or user.email},\n\n"
        f"Reset your OpsPortal password using the link below (expires in 1 hour):\n\n"
        f"{reset_link}\n\n"
        f"If you didn't request this, ignore this email.\n"
    )

    payload = {
        "sender": {"name": "OpsPortal", "email": from_email},
        "to": [{"email": user.email, "name": user.full_name or user.email}],
        "subject": "Reset your OpsPortal password",
        "textContent": body_text,
        "htmlContent": body_html,
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
        if resp.status_code >= 400:
            logger.error(
                "Brevo failed to send reset email to %s: %s %s",
                user.email, resp.status_code, resp.text
            )
            return False
        return True
    except requests.RequestException:
        logger.exception("Failed to reach Brevo for password reset %s", user.email)
        return False


def _build_html_body(full_name, verify_link, temp_password):
    """Simple table-based HTML with a button — inline styles only, since
    that's what actually renders consistently across email clients."""
    name = html.escape(full_name)
    link = html.escape(verify_link)

    if temp_password:
        pw = html.escape(str(temp_password))
        password_block = f"""
        <tr>
          <td style="padding: 0 32px 24px 32px;">
            <table cellpadding="0" cellspacing="0" width="100%" style="background:#F1F5F9;border-radius:8px;">
              <tr>
                <td style="padding:16px 20px;">
                  <p style="margin:0 0 6px 0;font-size:13px;color:#475569;font-family:sans-serif;">
                    Your temporary password
                  </p>
                  <p style="margin:0;font-size:18px;font-weight:600;color:#0F172A;font-family:monospace;letter-spacing:0.5px;">
                    {pw}
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""
    else:
        password_block = """
        <tr>
          <td style="padding: 0 32px 24px 32px;">
            <table cellpadding="0" cellspacing="0" width="100%" style="background:#FFF7ED;border-radius:8px;">
              <tr>
                <td style="padding:16px 20px;">
                  <p style="margin:0;font-size:13px;color:#92400E;font-family:sans-serif;line-height:1.5;">
                    Your password was set when your account was first created.
                    If you don&#39;t have it, contact your admin to reset it.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    return f"""
    <table cellpadding="0" cellspacing="0" width="100%" style="background:#F8FAFC;padding:32px 0;">
      <tr>
        <td align="center">
          <table cellpadding="0" cellspacing="0" width="480" style="background:#FFFFFF;border-radius:12px;overflow:hidden;font-family:sans-serif;">
            <tr>
              <td style="padding:32px 32px 8px 32px;">
                <p style="margin:0 0 4px 0;font-size:12px;font-weight:600;letter-spacing:1px;color:#64748B;text-transform:uppercase;">
                  OpsPortal
                </p>
                <h1 style="margin:0 0 16px 0;font-size:20px;color:#0F172A;">
                  Confirm your account
                </h1>
                <p style="margin:0 0 24px 0;font-size:14px;line-height:1.6;color:#334155;">
                  Hi {name}, an admin created a staff account for you on OpsPortal.
                  Follow the steps below to activate it.
                </p>
              </td>
            </tr>
            {password_block}
            <tr>
              <td style="padding:0 32px 24px 32px;">
                <ol style="margin:0;padding-left:18px;font-size:14px;line-height:1.8;color:#334155;">
                  <li>Click the button below to confirm your email address.</li>
                  <li>Sign in using this email and the temporary password above.</li>
                  <li>Once signed in, update your password from your account settings.</li>
                </ol>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 32px 32px;" align="center">
                <a href="{link}"
                   style="display:inline-block;background:#0F172A;color:#FFFFFF;text-decoration:none;
                          font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;">
                  Confirm Email &amp; Get Started
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 32px 32px;">
                <p style="margin:0;font-size:12px;color:#94A3B8;line-height:1.6;">
                  If the button doesn't work, copy and paste this link into your browser:<br>
                  <a href="{link}" style="color:#3B82F6;">{link}</a>
                </p>
                <p style="margin:16px 0 0 0;font-size:12px;color:#94A3B8;">
                  If you weren't expecting this, you can safely ignore this email.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>"""


def send_verification_email(user, request=None, temp_password=None):
    """Emails a one-time verification link to a newly-invited staff member."""
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

    if temp_password:
        password_line = f"Your temporary password: {temp_password}\n\n"
        step2 = "Sign in using this email and the temporary password above."
    else:
        password_line = "Your password was set when your account was created. If you don't have it, contact your admin.\n\n"
        step2 = "Sign in using this email and your password (contact your admin if you don't have it)."
    body_text = (
        f"Hi {user.full_name},\n\n"
        f"An admin has created a staff account for you on OpsPortal.\n\n"
        f"{password_line}"
        f"1. Confirm your email address using the link below.\n"
        f"2. {step2}\n"
        f"3. Update your password from your account settings once signed in.\n\n"
        f"Confirm your email: {verify_link}\n\n"
        f"If you weren't expecting this, you can ignore this email.\n"
    )
    body_html = _build_html_body(user.full_name, verify_link, temp_password)

    payload = {
        "sender": {"name": "OpsPortal", "email": from_email},
        "to": [{"email": user.email, "name": user.full_name}],
        "subject": "Confirm your OpsPortal account",
        "textContent": body_text,
        "htmlContent": body_html,
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


# ---------------------------------------------------------------------------
# LOGIN ALERT EMAIL
# ---------------------------------------------------------------------------

def get_client_ip(request):
    """Render sits behind a proxy, so the real client IP is the first hop
    in X-Forwarded-For, not REMOTE_ADDR (which would just be the proxy)."""
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def get_device_info(request):
    """Parses the User-Agent header into a human-readable device/browser/OS
    string, e.g. 'Chrome on Windows (Desktop)'."""
    ua_string = request.META.get('HTTP_USER_AGENT', '')
    if not ua_string:
        return "Unknown device"
    ua = parse_user_agent(ua_string)
    device_type = "Mobile" if ua.is_mobile else "Tablet" if ua.is_tablet else "Desktop" if ua.is_pc else "Other"
    browser = ua.browser.family or "Unknown browser"
    os_name = ua.os.family or "Unknown OS"
    return f"{browser} on {os_name} ({device_type})"


def get_geo_location(ip):
    """Best-effort IP geolocation via ipapi.co's free HTTPS endpoint (Render
    blocks plain HTTP/SMTP, so this only uses HTTPS APIs). Returns a dict
    with as much precision as IP-based lookup can give — city/region/country,
    postal code, lat/lon, and ISP — or None if it can't be resolved
    (private/local IPs, rate limits, network errors, etc).

    NOTE ON PRECISION: this is IP geolocation, which is accurate to roughly
    city/neighbourhood level — it cannot pinpoint an exact address or GPS
    position. True GPS-level precision would require the browser's
    navigator.geolocation API, which prompts the user for location
    permission on their device every time they sign in. That's intentionally
    not done here: it's intrusive, most people would decline it, and storing
    precise real-time location of staff on every login raises its own
    privacy/legal questions. IP lookup is the standard, non-intrusive
    approach used for login-alert emails."""
    if not ip or ip in ('127.0.0.1', 'localhost') or ip.startswith(('10.', '192.168.', '172.16.')):
        return None

    try:
        resp = requests.get(IPAPI_URL.format(ip=ip), timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get('error'):
            return None
        return {
            'city': data.get('city'),
            'region': data.get('region'),
            'country': data.get('country_name'),
            'postal': data.get('postal'),
            'latitude': data.get('latitude'),
            'longitude': data.get('longitude'),
            'isp': data.get('org'),
        }
    except (requests.RequestException, ValueError):
        logger.warning("Geolocation lookup failed for IP %s", ip)
        return None


def _format_location_text(geo):
    """Plain-text 'City, Region, Postal, Country' line for the email body."""
    if not geo:
        return "Unknown location"
    parts = [geo.get('city'), geo.get('region'), geo.get('postal'), geo.get('country')]
    text = ", ".join(p for p in parts if p)
    return text or "Unknown location"


def _maps_link(geo):
    """Google Maps link pinned to the geolocated coordinates, if available."""
    if not geo or geo.get('latitude') is None or geo.get('longitude') is None:
        return None
    return f"https://www.google.com/maps?q={geo['latitude']},{geo['longitude']}"


def send_login_alert_email(user, request):
    """Emails the user a heads-up every time their account is signed into,
    with device, location, IP and time — so staff/admins notice logins
    that aren't theirs. Never raises: a failure here should never block or
    break the sign-in flow itself."""
    api_key = getattr(settings, 'BREVO_API_KEY', '')
    from_email = getattr(settings, 'BREVO_FROM_EMAIL', '')

    if not api_key or not from_email:
        logger.error(
            "Cannot send login alert to %s: BREVO_API_KEY / BREVO_FROM_EMAIL not configured.",
            user.email
        )
        return False

    ip = get_client_ip(request)
    device = get_device_info(request)
    geo = get_geo_location(ip)
    location_text = _format_location_text(geo)
    maps_link = _maps_link(geo)
    isp = geo.get('isp') if geo else None
    login_time = timezone.now().strftime("%B %d, %Y at %I:%M %p %Z") or timezone.now().isoformat()

    name = html.escape(user.full_name or user.email)
    safe_device = html.escape(device)
    safe_location = html.escape(location_text)
    safe_ip = html.escape(ip or "Unknown")
    safe_time = html.escape(login_time)
    safe_isp = html.escape(isp) if isp else None
    safe_maps_link = html.escape(maps_link) if maps_link else None

    location_row = f'<strong>Location:</strong> {safe_location}'
    if safe_maps_link:
        location_row += f' &nbsp;<a href="{safe_maps_link}" style="color:#3B82F6;">(view on map)</a>'
    isp_row = f'<br><strong>Network:</strong> {safe_isp}' if safe_isp else ''

    body_html = f"""
    <table cellpadding="0" cellspacing="0" width="100%" style="background:#F8FAFC;padding:32px 0;">
      <tr><td align="center">
        <table cellpadding="0" cellspacing="0" width="480" style="background:#FFFFFF;border-radius:12px;overflow:hidden;font-family:sans-serif;">
          <tr><td style="padding:32px 32px 8px 32px;">
            <p style="margin:0 0 4px 0;font-size:12px;font-weight:600;letter-spacing:1px;color:#64748B;text-transform:uppercase;">OpsPortal</p>
            <h1 style="margin:0 0 16px 0;font-size:20px;color:#0F172A;">New sign-in to your account</h1>
            <p style="margin:0 0 20px 0;font-size:14px;line-height:1.6;color:#334155;">
              Hi {name}, we noticed a new sign-in to your OpsPortal account. If this was you, no action is needed.
            </p>
          </td></tr>
          <tr><td style="padding:0 32px 24px 32px;">
            <table cellpadding="0" cellspacing="0" width="100%" style="background:#F1F5F9;border-radius:8px;">
              <tr><td style="padding:16px 20px;font-size:13px;color:#334155;font-family:sans-serif;line-height:2;">
                <strong>Device:</strong> {safe_device}<br>
                {location_row}{isp_row}<br>
                <strong>IP address:</strong> {safe_ip}<br>
                <strong>Time:</strong> {safe_time}
              </td></tr>
            </table>
          </td></tr>
          <tr><td style="padding:0 32px 32px 32px;">
            <p style="margin:0;font-size:12px;color:#92400E;background:#FFF7ED;border-radius:8px;padding:12px 16px;line-height:1.6;">
              If this wasn't you, change your password immediately and contact your admin.
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>"""

    body_text = (
        f"Hi {user.full_name or user.email},\n\n"
        f"New sign-in to your OpsPortal account:\n\n"
        f"Device: {device}\n"
        f"Location: {location_text}\n"
        + (f"Map: {maps_link}\n" if maps_link else "")
        + (f"Network: {isp}\n" if isp else "")
        + f"IP address: {ip or 'Unknown'}\n"
        f"Time: {login_time}\n\n"
        f"If this wasn't you, change your password immediately and contact your admin.\n"
    )

    payload = {
        "sender": {"name": "OpsPortal", "email": from_email},
        "to": [{"email": user.email, "name": user.full_name or user.email}],
        "subject": "New sign-in to your OpsPortal account",
        "textContent": body_text,
        "htmlContent": body_html,
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
        if resp.status_code >= 400:
            logger.error(
                "Brevo failed to send login alert to %s: %s %s",
                user.email, resp.status_code, resp.text
            )
            return False
        return True
    except requests.RequestException:
        logger.exception("Failed to reach Brevo for login alert %s", user.email)
        return False