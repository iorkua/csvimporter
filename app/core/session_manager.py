"""Centralized in-memory session manager for upload previews.

This module wraps the plain dictionary previously stored on the FastAPI app
instance so routers and services can share state without circular imports.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, MutableMapping, Optional

from fastapi import HTTPException, status


SessionData = Dict[str, Any]
SessionStore = MutableMapping[str, SessionData]


_session_store: SessionStore = {}


def get_store() -> SessionStore:
    """Return the backing session dictionary."""
    return _session_store


def generate_session_id() -> str:
    """Return a new unique identifier for session entries."""
    return str(uuid.uuid4())


def has_session(session_id: str) -> bool:
    """Check whether the store contains a session id."""
    return session_id in _session_store


def get_session(session_id: str) -> Optional[SessionData]:
    """Fetch a session payload by id without raising."""
    return _session_store.get(session_id)


def require_session(session_id: str) -> SessionData:
    """Fetch a session payload, raising a 404 if it does not exist."""
    if session_id not in _session_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return _session_store[session_id]


def set_session(session_id: str, data: SessionData) -> None:
    """Add or replace a session payload."""
    _session_store[session_id] = data


def delete_session(session_id: str) -> None:
    """Remove a session from the store if present."""
    _session_store.pop(session_id, None)


def list_sessions() -> Iterable[str]:
    """Return an iterable of all session identifiers."""
    return tuple(_session_store.keys())
