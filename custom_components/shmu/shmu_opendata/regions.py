"""Outlines of the warning regions whose CAP alerts carry no polygon.

SHMÚ issues each alert for one warning region: a district (okres), with the
city districts of Bratislava and of Košice merged into one region each, 72 in
all. An alert names its region by a Meteoalarm ``EMMA_ID`` geocode and usually
also carries the region's outline as a ``<polygon>``, which the parser prefers.
Alerts for Piešťany carry the geocode alone, so this table supplies their
outline. Without it they would have no geometry, and an alert without
geometry covers the whole country.

Verified 2026-11-26 over the whole CAP archive (21 days, 1259 alerts): every
alert has exactly one area with an ``EMMA_ID``, the other 71 regions always
send a polygon, identical in all their alerts, and Piešťany (SK204) never does.
A region that starts arriving without a polygon makes the parser reject its
alerts, which the daily live test reports, and then needs an entry here.

Provenance - regenerate from the district map that SHMÚ's own warnings page
(https://www.shmu.sk/sk/?page=987) draws::

    # https://www.shmu.sk/assets/maps/meteo_map.json
    #   GeoJSON FeatureCollection, one Polygon per region (only Košice okolie
    #   has a hole), properties ID, SKRATKA and NAZOV_OKRE.
    # ID is not the EMMA_ID number (Bratislava is 101 but SK100, the Košice
    # region's 80x are SK12x). Match a feature to an alert by SKRATKA, the
    # suffix after the last "_" of the alert's <identifier> ("..._PN").
    # Vertices are (lon, lat): store them as CAP does, "lat,lon lat,lon ...",
    # rounded to six decimals.

The map traces the boundaries a little differently from the CAP polygons:
Piešťany's outline lies a median of 80 m and at most 340 m from its
neighbours' polygons, so a point that close to the boundary can get both
districts' warnings or neither's. Every station and rain gauge falls in
exactly one region.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

#: ``EMMA_ID`` -> the region's outline, as the text of a CAP ``<polygon>``.
REGION_POLYGONS: Final[Mapping[str, str]] = {
    # Piešťany (map SKRATKA PN)
    "SK204": (
        "48.678096,17.715172 48.668680,17.730147 48.662125,17.731695 "
        "48.651969,17.745590 48.651309,17.751026 48.647055,17.759785 "
        "48.641734,17.780038 48.637264,17.790151 48.639914,17.794109 "
        "48.637590,17.805857 48.640600,17.810049 48.639868,17.821913 "
        "48.647135,17.825589 48.650399,17.822382 48.653627,17.827177 "
        "48.651508,17.840809 48.644208,17.839767 48.641023,17.845979 "
        "48.637987,17.846059 48.632743,17.857848 48.638030,17.859920 "
        "48.638180,17.873216 48.630475,17.886589 48.631387,17.897870 "
        "48.627325,17.904695 48.625599,17.911547 48.625510,17.924996 "
        "48.622279,17.932652 48.621544,17.941880 48.622498,17.958177 "
        "48.617557,17.959835 48.611903,17.965184 48.613020,17.980562 "
        "48.605911,17.981706 48.601973,17.986900 48.597182,17.984716 "
        "48.596766,17.978012 48.591528,17.975841 48.591046,17.951285 "
        "48.583514,17.954308 48.582084,17.925623 48.589160,17.914796 "
        "48.593170,17.902838 48.592859,17.897230 48.570517,17.885446 "
        "48.570288,17.882274 48.561989,17.872916 48.551693,17.870611 "
        "48.545044,17.865200 48.533243,17.866559 48.524921,17.857156 "
        "48.522051,17.846967 48.519806,17.843804 48.522488,17.836056 "
        "48.516236,17.819093 48.504161,17.823259 48.499256,17.812043 "
        "48.497404,17.801215 48.502110,17.793741 48.511082,17.792793 "
        "48.520164,17.771672 48.509857,17.767924 48.508044,17.776353 "
        "48.500101,17.768392 48.495971,17.769890 48.488307,17.767394 "
        "48.486645,17.753214 48.477793,17.747546 48.472835,17.747572 "
        "48.473237,17.737737 48.475592,17.719064 48.479687,17.706790 "
        "48.490228,17.689729 48.494503,17.680848 48.505994,17.667880 "
        "48.514095,17.662838 48.509973,17.657968 48.514272,17.646847 "
        "48.524671,17.633902 48.528978,17.637218 48.538122,17.625309 "
        "48.540260,17.616076 48.543730,17.615764 48.557347,17.599013 "
        "48.568599,17.590957 48.569179,17.585305 48.574894,17.580726 "
        "48.576099,17.570451 48.573263,17.565588 48.575476,17.559707 "
        "48.582118,17.558373 48.589338,17.561574 48.594616,17.566834 "
        "48.593272,17.571210 48.595440,17.578052 48.604408,17.576391 "
        "48.607995,17.571186 48.611418,17.573282 48.619652,17.585349 "
        "48.622964,17.578891 48.626618,17.577121 48.633403,17.580496 "
        "48.638241,17.579285 48.638703,17.592037 48.641927,17.602025 "
        "48.640612,17.606303 48.644981,17.626903 48.648916,17.620655 "
        "48.652169,17.622673 48.657974,17.617995 48.662665,17.617217 "
        "48.670479,17.619753 48.668738,17.627488 48.662084,17.635477 "
        "48.664858,17.639231 48.663346,17.647908 48.665868,17.664175 "
        "48.668758,17.667585 48.670243,17.678123 48.678894,17.689002 "
        "48.676278,17.694183 48.683011,17.703406 48.678096,17.715172"
    ),
}
