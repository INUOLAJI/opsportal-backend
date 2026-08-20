# OpsPortal — Backend

Django + Django REST Framework API for OpsPortal, with real-time updates over
WebSockets (Django Channels) and file storage on Cloudinary.

## Stack

- Django 5.1 / Django REST Framework
- PostgreSQL (via `psycopg` v3)
- Django Channels + Daphne (ASGI, WebSockets) — Redis-backed in production,
  falls back to an in-memory channel layer if `REDIS_URL` isn't set (fine for
  local dev, not for multi-process production)
- JWT auth via `djangorestframework-simplejwt`
- Cloudinary for document storage

## Project layout

```
app/
  core/            # settings, ASGI/WSGI entrypoints, root URLconf
  api/
    models.py       # User, Task, ActivityLog, Booking, Document, Invoice, PlatformSettings
    serializers.py
    views.py
    urls.py
    permissions.py  # IsAdminUser, IsOwnerOrAdmin
    consumers.py     # WebSocket consumer for real-time task/activity updates
    routing.py       # WebSocket URL routing
    jwt_auth_middleware.py  # authenticates WS connections via ?token=
requirements.txt
```

## Data model

- **User** — custom user model (`api.User`), email as username, `role` is
  `staff` or `admin`.
- **Task** — internal to-dos. `status` (pending/in_progress/overdue/complete),
  `priority` (low/medium/high/urgent), `assignee`, `completion_requested`
  (staff flag it for review; only an admin can actually set `status=complete`).
- **ActivityLog** — feeds the notification bell / activity feed. `read_by` is
  a per-user M2M so each admin has independent read state.
- **Booking** — client self-scheduling.
- **Document** — Cloudinary-backed uploads, optional `assigned_to` so an
  admin can share a doc directly into a specific staff member's view.
- **Invoice** — billing records tied to a client and optionally a booking.
- **PlatformSettings** — single global row (enforced via `PlatformSettings.load()`)
  backing the Settings page: workspace title, environment stage, notification
  toggles, MFA enforcement flag, and secret-key rotation timestamp.

## Permissions model

- Staff only ever see their **own** tasks, documents, bookings, and invoices.
  Admins see everything.
- Only admins can create/edit/delete tasks, and only admins can PATCH
  `PlatformSettings` or rotate the secret key — staff get 403s.
- Staff flag a task done via `POST /tasks/<id>/request-completion/`; an admin
  still has to confirm by setting `status=complete`.
- Login no longer checks a `role` sent by the client against `user.role` —
  the frontend has one shared sign-in page for both admins and staff, and
  the account's real role is looked up server-side and returned in the
  response, not asserted by the caller.

## Staff email verification

Admin-created staff accounts start with `is_verified=False` and can't sign
in until they click the link emailed to them (see `tokens.py` /
`send_verification_email`). Admin accounts are verified implicitly on
signup (no inviter to send a link from).

Delivery goes through **Brevo's HTTP API**, not SMTP — Render's free tier
blocks all outbound SMTP ports (25/465/587) regardless of provider or
credentials, so `django.core.mail`'s SMTP backend can never connect from
there. Brevo's API runs over HTTPS (443), which Render always allows.
(Earlier attempts — a Supabase Edge Function + Resend, then Gmail SMTP,
then SendGrid — were dropped for domain-verification friction, the SMTP
port block, and a signup blocker, respectively.)

Requires `BREVO_API_KEY` and `BREVO_FROM_EMAIL` (see Environment variables
below). `BREVO_FROM_EMAIL` only needs **single-sender verification** in
Brevo's dashboard (click a confirmation link) — no domain DNS setup
required.

## API endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/signup/` | staff created this way are `is_verified=False` until they confirm via email |
| POST | `/api/auth/signin/` | returns access + refresh tokens; blocks unverified staff (403, `code: "email_not_verified"`) |
| POST | `/api/auth/token/refresh/` | |
| POST | `/api/auth/verify-email/` | `{uid, token}` from the emailed link — sets `is_verified=True` |
| POST | `/api/auth/resend-verification/` | `{email}` — always returns 200 (doesn't leak whether the account exists) |
| GET | `/api/users/` | team list, for assignee pickers. Optional `?role=staff` or `?role=admin` to filter |
| GET/POST | `/api/tasks/` | list scoped by role; create is admin-only |
| GET/PATCH/DELETE | `/api/tasks/<id>/` | update/delete is admin-only |
| POST | `/api/tasks/<id>/request-completion/` | staff-only, own tasks |
| GET | `/api/activity/` | scoped by role |
| POST | `/api/activity/mark-all-read/` | |
| GET/POST | `/api/bookings/` | |
| GET/PATCH/DELETE | `/api/bookings/<id>/` | |
| GET/POST | `/api/documents/` | multipart upload |
| GET/PATCH/DELETE | `/api/documents/<id>/` | |
| GET/POST | `/api/invoices/` | |
| GET/PATCH/DELETE | `/api/invoices/<id>/` | |
| GET/PATCH | `/api/settings/` | PATCH is admin-only |
| POST | `/api/settings/rotate-secret/` | admin-only |

WebSocket: `ws(s)://<host>/ws/dashboard/?token=<access_token>` — broadcasts
`task.created`, `task.updated`, and `activity.created` events to the admin
group and to each staff member's personal group.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | recommended | falls back to a random key per-process if unset — fine for dev, not for prod (sessions/tokens won't survive a restart) |
| `DEBUG` | no | `1`/`true` to enable, default off |
| `ALLOWED_HOSTS` | prod | space-separated |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | yes | |
| `REDIS_URL` | prod | enables the Redis channel layer for Channels; without it, WebSocket broadcast only works within a single process |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | yes | document uploads |
| `BREVO_API_KEY` | yes (for staff invites) | from Brevo dashboard → account menu → SMTP & API → API Keys |
| `BREVO_FROM_EMAIL` | yes (for staff invites) | must be verified under Brevo → Senders, Domains & Dedicated IPs → Senders |
| `FRONTEND_URL` | recommended | used to build the verification link staff click; defaults to the deployed Vercel URL |

## Local setup

```bash
python -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install -r requirements.txt

# .env — see the table above
cd app
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver          # daphne-backed, serves HTTP + WS on one port
```

CORS is currently allowlisted for `localhost:3000`, `localhost:5173`, and
`127.0.0.1:3000` (see `CORS_ALLOWED_ORIGINS` in `core/settings.py`) — add your
frontend's origin there if it differs.

## Migrations

After pulling model changes, always run:

```bash
python manage.py makemigrations api
python manage.py migrate
```

Don't hand-copy someone else's generated migration file into this repo —
migration numbering depends on what's already applied locally; always
generate your own from the current `models.py`.