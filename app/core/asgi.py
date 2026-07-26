"""
ASGI config for the project.

Serves regular HTTP through Django as usual, and WebSocket connections
through Channels — routed to api/routing.py and authenticated via the
custom JWT middleware in api/jwt_auth_middleware.py (since this project
uses JWT auth, not Django sessions, so the standard session-based
AuthMiddlewareStack won't authenticate socket connections here).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# IMPORTANT: get_asgi_application() must run before importing anything that
# touches models (consumers, routing) — otherwise Django raises
# AppRegistryNotReady.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from api.jwt_auth_middleware import JWTAuthMiddlewareStack  # noqa: E402
from api.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})