"""Request-scoped context for request_id tracing."""
from __future__ import annotations

import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    """Generate a new request ID and set it in context."""
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_var.get()
