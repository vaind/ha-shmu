"""Exceptions raised by the SHMÚ open-data client.

These are intentionally explicit so callers (e.g. a Home Assistant
coordinator) can distinguish transient connectivity problems from
malformed-data problems and react accordingly.
"""

from __future__ import annotations


class ShmuError(Exception):
    """Base class for all errors raised by this package."""


class ShmuConnectionError(ShmuError):
    """A network/HTTP problem occurred while talking to the server."""


class ShmuDataError(ShmuError):
    """The server responded but the payload could not be parsed."""
