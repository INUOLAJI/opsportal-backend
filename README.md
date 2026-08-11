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

## API endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/signup/` | |
| POST | `/api/auth/signin/` | returns access + refresh tokens |
| POST | `/api/auth/token/refresh/` | |
| GET | `/api/users/` | team list, for assignee pickers |
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