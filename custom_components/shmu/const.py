"""Constants for the SHMÚ Weather integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "shmu"

CONF_IND_KLI: Final = "ind_kli"

#: Observations refresh every 5 min upstream; poll a little slower and rely on
#: the client's change-detection so the large body is rarely re-downloaded.
UPDATE_INTERVAL: Final = timedelta(minutes=10)

#: SHMÚ data is CC BY 4.0 and must be attributed wherever it is shown.
ATTRIBUTION: Final = "Data © Slovenský hydrometeorologický ústav (SHMÚ), CC BY 4.0"

MANUFACTURER: Final = "Slovenský hydrometeorologický ústav"
