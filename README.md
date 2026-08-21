# OpsPortal — Backend

A multi-tenant operations management API built with Django REST Framework. Handles authentication, task management, document storage, bookings, invoices, activity logging, and real-time WebSocket updates.

---

## Live API

**Base URL:** `https://opsportal-backend-n1jf.onrender.com/api`

**Swagger UI:** [/api/schema/swagger/](https://opsportal-backend-n1jf.onrender.com/api/schema/swagger/)

**ReDoc:** [/api/schema/redoc/](https://opsportal-backend-n1jf.onrender.com/api/schema/redoc/)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.1, Django REST Framework 3.15 |
| Auth | JWT via `djangorestframework-simplejwt` |
| Database | PostgreSQL (Supabase) via `psycopg` v3 |
| Real-time | Django Channels 4 + Daphne (WebSockets) |
| Channel Layer | Redis (Upstash) |
| File Storage | Cloudinary via `django-cloudinary-storage` |
| Email | Brevo HTTP API (SMTP blocked on Render free tier) |
| API Docs | `drf-spectacular` (Swagger / ReDoc) |
| Hosting | Render (ASGI via Daphne) |

---

## Features

- Multi-tenant isolation — every resource is scoped to a `Company`
- Admin and staff roles with separate permission levels
- Staff invite flow — admin creates staff account, Brevo sends verification email with temp password
- Staff profile completion form on first login (set full name, email, new password)
- Forgot / reset password via emailed token link
- JWT authentication with access token refresh and refresh token blacklisting on logout
- Tasks with multi-assignee support (ManyToMany), priority levels, due dates, and completion request workflow
- File attachments on tasks (Cloudinary, 10MB limit)
- Document vault with per-staff assignment
- Bookings, invoices, activity log, and platform settings per company
- Real-time WebSocket push for task and activity events (no polling needed)

---

## Project Structure

```
backend/
└── app/
    ├── api/
    │   ├── migrations/         # Database migrations
    │   ├── models.py           # Company, User, Task, TaskAttachment,
    │   │                       # ActivityLog, Booking, Document,
    │   │                       # Invoice, PlatformSettings
    │   ├── serializers.py      # DRF serializers for all models
    │   ├── views.py            # All API views and auth endpoints
    │   ├── urls.py             # URL routing
    │   ├── tokens.py           # Email verification + password reset
    │   │                       # token generators and Brevo email helpers
    │   ├── consumers.py        # WebSocket consumer (Channels)
    │   ├── routing.py          # WebSocket URL routing
    │   ├── jwt_auth_middleware.py  # Token auth for WS connections
    │   └── permissions.py      # IsOwnerOrAdmin, IsAdminUser
    └── core/
        ├── settings.py
        ├── urls.py
        ├── asgi.py             # ASGI entry point (HTTP + WebSocket)
        └── wsgi.py
```

---

## API Endpoints

### Auth — `/api/auth/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/auth/signup/` | No | Register a new admin + company |
| POST | `/auth/signin/` | No | Sign in, returns JWT tokens |
| POST | `/auth/verify-email/` | No | Verify staff email, returns JWT tokens |
| POST | `/auth/resend-verification/` | No | Resend verification email |
| POST | `/auth/forgot-password/` | No | Send password reset email |
| POST | `/auth/reset-password/` | No | Reset password via uid + token |
| POST | `/auth/complete-profile/` | Yes | Staff first-login: set name, email, password |
| POST | `/auth/change-password/` | Yes | Change password (staff skip current password check) |
| POST | `/auth/token/refresh/` | No | Refresh access token |

### Tasks — `/api/tasks/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/tasks/` | Yes | List tasks (admin: all; staff: assigned only) |
| POST | `/tasks/` | Admin | Create a task |
| GET | `/tasks/<id>/` | Yes | Get task detail |
| PATCH | `/tasks/<id>/` | Admin | Update task |
| DELETE | `/tasks/<id>/` | Admin | Delete task |
| POST | `/tasks/<id>/request-completion/` | Staff | Flag task as done for admin review |
| POST | `/tasks/<id>/attachments/` | Yes | Upload file attachment (max 10MB) |
| DELETE | `/tasks/<id>/attachments/<att_id>/` | Yes | Delete attachment |

### Documents — `/api/documents/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/documents/` | Yes | List documents (admin: all; staff: own + assigned) |
| POST | `/documents/` | Yes | Upload document to vault |
| DELETE | `/documents/<id>/` | Yes | Delete document |

### Activity — `/api/activity/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/activity/` | Yes | List recent activity (last 20) |
| POST | `/activity/mark-all-read/` | Yes | Mark all activity as read |

### Users — `/api/users/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/users/` | Yes | List company users (filter with `?role=staff`) |
| DELETE | `/users/<id>/` | Admin | Remove a team member |

### Bookings — `/api/bookings/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/bookings/` | Yes | List bookings |
| POST | `/bookings/` | Yes | Create booking |
| GET/PATCH/DELETE | `/bookings/<id>/` | Yes | Manage booking |

### Invoices — `/api/invoices/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/invoices/` | Yes | List invoices |
| POST | `/invoices/` | Yes | Create invoice |
| GET/PATCH/DELETE | `/invoices/<id>/` | Yes | Manage invoice |

### Settings — `/api/settings/`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/PATCH | `/settings/` | Yes | Get or update platform settings (PATCH: admin only) |
| POST | `/settings/rotate-secret/` | Admin | Rotate secret key timestamp |

---

## Data Models

### Company
Multi-tenancy root. Every user, task, document, booking, invoice, and activity belongs to a company.

### User
Custom user model extending `AbstractBaseUser`. Fields: `email`, `full_name`, `role` (admin/staff), `company` (FK), `is_verified`, `is_active`.

### Task
`title`, `tag`, `assignee` (FK, legacy single), `assignees` (M2M, multi-assignee), `status`, `priority`, `completion_requested`, `due_date`, `created_by`, `company`.

### TaskAttachment
`task` (FK), `uploaded_by` (FK), `file` (Cloudinary), `filename`, `file_size_mb`.

### Document
`title`, `category`, `file` (Cloudinary), `uploaded_by`, `assigned_to` (single FK), `company`.

### ActivityLog
`user`, `action`, `related_task`, `company`, `read_by` (M2M for per-user read state).

---

## WebSocket

**URL:** `wss://opsportal-backend-n1jf.onrender.com/ws/dashboard/?token=<access_token>`

Token is passed as a query param because browsers can't set custom headers on WebSocket connections.

**Events pushed to client:**

| Event type | Payload key | Trigger |
|---|---|---|
| `task_created` | `task` | New task created |
| `task_updated` | `task` | Task status/fields changed |
| `activity_created` | `activity` | New activity log entry |

---

## Local Setup

### Prerequisites
- Python 3.11+
- PostgreSQL (or a Supabase project)
- Redis (or Upstash Redis for the channel layer)

### Installation

```bash
git clone <repo-url>
cd backend

python -m venv .venv
# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in `backend/`:

```env
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# PostgreSQL
POSTGRES_DB=postgres
POSTGRES_USER=postgres.your-project-ref
POSTGRES_PASSWORD=your-password
POSTGRES_HOST=aws-0-eu-west-1.pooler.supabase.com
POSTGRES_PORT=6543

# Redis (channel layer)
REDIS_URL=redis://localhost:6379

# Cloudinary
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# Brevo (email)
BREVO_API_KEY=your-brevo-api-key
BREVO_FROM_EMAIL=noreply@yourdomain.com

# Frontend URL (used in email links)
FRONTEND_URL=http://localhost:5173
```

### Run

```bash
cd app
python manage.py migrate
python manage.py runserver
```

> The server runs via Daphne (ASGI) which handles both HTTP and WebSocket connections on the same port.

---

## Deployment (Render)

- Runtime: Python 3.11
- Build command: `pip install -r requirements.txt`
- Start command: `cd app && daphne -b 0.0.0.0 -p $PORT core.asgi:application`
- All environment variables set in Render dashboard
- Migrations must be written manually (no `manage.py` access on Render free tier)

> **Note:** Render free tier spins down after inactivity. The first request after a cold start may fail with a CORS-like error — this is a timeout, not a CORS misconfiguration. Use [cron-job.org](https://cron-job.org) to ping the API every 10 minutes to keep it warm.

---

## License

MIT
