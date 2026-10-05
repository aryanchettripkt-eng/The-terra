"""Shared SQL for resolving a candidate site's hazard regime.

A site's regime is the regime of the H3 res-8 cell containing its centroid
(`hazard_static_flood.hazard_regime`). Both the site listing and the allocation query use this
one fragment, so they cannot disagree about whether a parcel sits on a char or in the channel.
"""

#: `LEFT JOIN` that exposes `reg.hazard_regime` for the candidate site aliased `cs`.
#: NULL when the district has no regime layer, which the eligibility policy does not treat as blocked.
SITE_REGIME_JOIN = """
            LEFT JOIN LATERAL (
                SELECT f.hazard_regime
                FROM grid_cell g
                JOIN hazard_static_flood f ON f.h3 = g.h3
                WHERE g.res = 8 AND ST_Contains(g.geom, cs.centroid::geometry)
                LIMIT 1
            ) reg ON true
"""
