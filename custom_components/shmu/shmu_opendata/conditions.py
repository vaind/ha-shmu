"""Map SHMÚ ``stav_poc`` weather-state codes to Home Assistant conditions.

SHMÚ does not publish the ``stav_poc`` code list in the open-data metadata.
The values come from *automatic* stations and follow **WMO code table 4680**
(``wawa`` — present weather reported from automatic stations, 0-99), the
international standard SHMÚ's AWS network uses. Live data confirms the range
in use (observed values include 0, 4, 30, 40, 51, 61, 62).

Hard limitation: ``wawa`` describes *present weather only* — it carries no
cloud-cover information. ``0`` means "no significant weather observed", **not**
"clear sky" (a station can report ``0`` while overcast). So this mapping can
identify precipitation/fog/thunder but cannot distinguish sunny / partly
cloudy / cloudy. When ``wawa`` says nothing is happening we return ``None``
(caller surfaces "unknown") rather than fabricate a sky state — the proper
condition comes from a cloud-aware source (SHMÚ website now, ALADIN later).

Reference: WMO-No. 306 Manual on Codes, code table 4680.
"""

from __future__ import annotations

# Home Assistant weather condition strings (homeassistant.components.weather).
CLOUDY = "cloudy"
FOG = "fog"
HAIL = "hail"
LIGHTNING = "lightning"
LIGHTNING_RAINY = "lightning-rainy"
POURING = "pouring"
RAINY = "rainy"
SNOWY = "snowy"
SNOWY_RAINY = "snowy-rainy"
WINDY = "windy"


def condition_from_weather_code(
    code: int | None, *, precipitation: float | None = None
) -> str | None:
    """Translate a ``stav_poc`` (WMO 4680 *wawa*) code to an HA condition.

    ``precipitation`` (1-minute sum, mm) is a last-resort hint used only when
    the code conveys no present weather. Returns ``None`` when the weather
    cannot be determined — the caller must treat that as "unknown" rather than
    invent a sky state.
    """
    if code is None:
        return RAINY if precipitation else None

    # 0-3: no significant weather / clouds (dis)forming — sky state unknown.
    if code <= 3:
        return RAINY if precipitation else None
    # 4-5: haze, smoke or dust in suspension (reduced visibility).
    if code in (4, 5):
        return FOG
    # 10 mist, 11 diamond dust, 12 distant lightning, 18 squalls.
    if code == 10:
        return FOG
    if code == 11:
        return SNOWY
    if code == 12:
        return LIGHTNING
    if code == 18:
        return WINDY
    # 20-29: precipitation/fog/thunder during the *preceding hour*, not now.
    if 20 <= code <= 29:
        return RAINY if precipitation else None
    # 30-35: fog or ice fog.
    if 30 <= code <= 35:
        return FOG
    # 40-42: precipitation of unknown type (42 = heavy).
    if 40 <= code <= 42:
        return POURING if code == 42 else RAINY
    # 50-59: drizzle. 54-56 freezing; 57-58 drizzle and rain.
    if 50 <= code <= 59:
        if code in (54, 55, 56):
            return SNOWY_RAINY
        return POURING if code == 53 else RAINY
    # 60-69: rain. 62-63 moderate/heavy, 64-66 freezing, 67-68 rain and snow.
    if 60 <= code <= 69:
        if code in (64, 65, 66, 67, 68):
            return SNOWY_RAINY
        return POURING if code in (62, 63) else RAINY
    # 70-79: solid precipitation, not showers. 74-76 ice pellets.
    if 70 <= code <= 79:
        return HAIL if code in (74, 75, 76) else SNOWY
    # 80-84: rain showers (82 heavy/violent → pouring).
    if 80 <= code <= 82:
        return POURING if code == 82 else RAINY
    # 83-84: mixed rain/snow showers.
    if code in (83, 84):
        return SNOWY_RAINY
    # 85-88: snow showers.
    if 85 <= code <= 88:
        return SNOWY
    # 89: hail / graupel showers.
    if code == 89:
        return HAIL
    # 90-99: thunderstorm. 96/99 with hail; 91-92 without precipitation.
    if code in (96, 99):
        return HAIL
    if code in (91, 92):
        return LIGHTNING
    if 90 <= code <= 99:
        return LIGHTNING_RAINY
    # Uncovered / reserved wawa codes (e.g. 6-9, 13-17, 19, 43-49): honest
    # "unknown" rather than fabricating an alarming state, matching the
    # module's stated philosophy and the `code <= 3` branch.
    return RAINY if precipitation else None
