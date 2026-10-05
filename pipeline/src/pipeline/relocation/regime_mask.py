"""Rasterises the hazard-regime layer into a mask of land that must not host a relocation site.

Char-belt and channel cells are where the flood layer says the ground is a river sandbar or river
water. A resettlement site there would be tomorrow's source, so those cells are blocked from the
candidate-site search outright (Phase 2e), regardless of how low the pixel-level susceptibility is.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features

from core.domain.regime import DEFAULT_REGIME_POLICY

logger = logging.getLogger("setu_pipeline.regime_mask")


def rasterize_blocked_regimes(
    cells: gpd.GeoDataFrame,
    shape: tuple[int, int],
    transform: rasterio.Affine,
    crs: Any,
    blocked_regimes: Iterable[str] = DEFAULT_REGIME_POLICY.blocked_destination_regimes,
) -> np.ndarray:
    """True where a pixel falls inside an H3 cell whose `hazard_regime` is blocked.

    `cells` is the flood H3 GeoParquet (EPSG:4326 polygons with a `hazard_regime` column).
    """
    blocked = set(blocked_regimes)
    selected = cells[cells["hazard_regime"].isin(blocked)]
    if selected.empty:
        return np.zeros(shape, dtype=bool)
    shapes = [(geom, 1) for geom in selected.to_crs(crs).geometry if geom is not None and not geom.is_empty]
    return features.rasterize(shapes, out_shape=shape, transform=transform, dtype=np.uint8).astype(bool)


def load_blocked_regime_mask(
    parquet_path: Path,
    shape: tuple[int, int],
    transform: rasterio.Affine,
    crs: Any,
    blocked_regimes: Iterable[str] = DEFAULT_REGIME_POLICY.blocked_destination_regimes,
) -> Optional[np.ndarray]:
    """Mask from the district's flood parquet, or None when no regime layer exists.

    None means "no regime data", which leaves the gate off; the caller records that gap so an
    unscreened district is never mistaken for a screened one.
    """
    if not parquet_path.is_file():
        logger.warning("No flood parquet at %s; regime gate not applied", parquet_path)
        return None
    cells = gpd.read_parquet(parquet_path)
    if "hazard_regime" not in cells.columns or cells["hazard_regime"].isna().all():
        logger.warning("%s carries no hazard_regime; regime gate not applied", parquet_path.name)
        return None
    return rasterize_blocked_regimes(cells, shape, transform, crs, blocked_regimes)
