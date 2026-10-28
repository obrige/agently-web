"""agently-web — Agently (QQ Mail Agent) protocol client and web server."""

from .client import (
    API_BASE,
    AUTH_BASE,
    CLI_VERSION,
    WEB_BASE,
    AgentlyApi,
    ApiError,
    Auth,
    DeviceAuthorization,
)
from .normalize import messages_of, normalise_me, pagination_of
from .store import AccountStore

__all__ = [
    "API_BASE",
    "AUTH_BASE",
    "WEB_BASE",
    "CLI_VERSION",
    "AgentlyApi",
    "ApiError",
    "Auth",
    "DeviceAuthorization",
    "AccountStore",
    "normalise_me",
    "messages_of",
    "pagination_of",
]

__version__ = "1.1.0"
