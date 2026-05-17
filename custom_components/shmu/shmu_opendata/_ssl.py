"""TLS context construction for opendata.shmu.sk.

The SHMÚ server presents only its leaf certificate and omits the Sectigo
intermediate ("Sectigo Public Server Authentication CA DV R36"), so a normal
client cannot build a path to the trusted root and verification fails.

The correct fix is **not** to disable verification but to supply the missing
intermediate. We ship it (fetched from the certificate's own AIA extension)
and add it to an otherwise-standard trust store, so the leaf is still fully
verified against the system/Mozilla root set.
"""

from __future__ import annotations

import ssl
from importlib import resources

_INTERMEDIATE = "shmu_intermediate.pem"


def create_ssl_context() -> ssl.SSLContext:
    """Return an SSL context that verifies opendata.shmu.sk.

    Performs blocking file I/O (reading the bundled certificate); call it from
    an executor when running under an event loop.
    """
    context = ssl.create_default_context()
    pem = (
        resources.files(__package__)
        .joinpath("certs", _INTERMEDIATE)
        .read_text(encoding="ascii")
    )
    context.load_verify_locations(cadata=pem)
    return context
