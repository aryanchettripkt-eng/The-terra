"""NDEM / NRSC reference flood inundation extraction and H3 zonal aggregation.

Extracts, filters, and rasterizes independent ISRO NDEM flood inundation polygons:
- Filters out non-flooded/nodata background polygons (gridcode == 0).
- Rasterizes flood extents onto a metric grid.
- Computes exact zonal flood fraction per H3 cell via exactextract.
- Computes multi-year recurrence and true coverage-normalized frequency.
- Segregates pre-2015 subset for non-circular evaluation.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Sequence, Tuple
import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import rasterio
from shapely.geometry import Polygon, box
import exactextract
import h3


def load_ndem_polygons(
    parquet_path: str | Path,
    bbox_wgs84: tuple[float, float, float, float] | None = None,
    filter_gridcode: bool = True,
) -> gpd.GeoDataFrame:
    """Load NDEM historical flood polygons, optionally clipping to AOI.

    Resolves critical diagnostics finding (§2.2):
    In 2011, 2012, 2013, NDEM contains gridcode==0.0 (background/nodata).
    These are strictly filtered out when filter_gridcode is True.

    Args:
        parquet_path: Path to NDEM parquet file.
        bbox_wgs84: Optional (min_lon, min_lat, max_lon, max_lat) bounding box.
        filter_gridcode: If True, drops polygons where gridcode == 0.0.

    Returns:
        GeoDataFrame of flood inundation polygons in EPSG:4326.
    """
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(f"NDEM reference file not found at: {path}")

    # Read parquet
    gdf = gpd.read_parquet(path)

    # Filter to AOI if provided
    if bbox_wgs84 is not None:
        min_lon, min_lat, max_lon, max_lat = bbox_wgs84
        clip_box = box(min_lon, min_lat, max_lon, max_lat)
        gdf = gdf[gdf.intersects(clip_box)].copy()

    # Ensure 'year' column exists
    if "year" not in gdf.columns:
        if "from_time" in gdf.columns:
            gdf["year"] = pd.to_datetime(gdf["from_time"], dayfirst=True, errors="coerce").dt.year.fillna(2021).astype(int)
        else:
            import re
            m = re.search(r"(19\d\d|20\d\d)", path.stem)
            default_year = int(m.group(1)) if m else 2021
            gdf["year"] = default_year

    # Filter out gridcode == 0.0 background
    if filter_gridcode and "gridcode" in gdf.columns:
        valid_flood_mask = gdf["gridcode"].isna() | (gdf["gridcode"] != 0.0)
        gdf = gdf[valid_flood_mask].copy()

    # Repair any invalid geometries
    if not gdf.empty:
        gdf["geometry"] = gdf["geometry"].buffer(0)

    return gdf


def rasterize_flood_polygons(
    gdf: gpd.GeoDataFrame,
    bounds: tuple[float, float, float, float],
    res: float = 20.0,
    target_crs: str = "EPSG:32645",
) -> tuple[np.ndarray, rasterio.Affine]:
    """Rasterize vector polygons into a 2D binary uint8 raster grid.

    Args:
        gdf: GeoDataFrame containing polygons.
        bounds: (minx, miny, maxx, maxy) in target metric CRS.
        res: Grid cell size in meters (default 20.0m).
        target_crs: Projected metric CRS (e.g. 'EPSG:32645').

    Returns:
        Tuple of (binary_raster_array, affine_transform).
    """
    minx, miny, maxx, maxy = bounds
    # Add small margin
    minx -= 500.0
    miny -= 500.0
    maxx += 500.0
    maxy += 500.0

    width = max(1, int(np.ceil((maxx - minx) / res)))
    height = max(1, int(np.ceil((maxy - miny) / res)))
    transform = from_bounds(minx, miny, maxx, maxy, width, height)

    if gdf.empty:
        return np.zeros((height, width), dtype=np.uint8), transform

    # Ensure projected to target CRS
    if gdf.crs is None or str(gdf.crs).lower() != target_crs.lower():
        gdf_proj = gdf.to_crs(target_crs)
    else:
        gdf_proj = gdf

    shapes = (
        (geom, 1)
        for geom in gdf_proj.geometry
        if geom is not None and not geom.is_empty
    )
    raster = rasterize(
        shapes=shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    return raster, transform


def extract_zonal_fractions_from_raster(
    raster: np.ndarray,
    transform: rasterio.Affine,
    crs: str,
    cells_gdf_proj: gpd.GeoDataFrame,
) -> np.ndarray:
    """Extract zonal mean flood fraction per H3 cell polygon using exactextract.

    Args:
        raster: 2D numpy array (e.g. uint8 binary flood mask).
        transform: Affine transform of raster.
        crs: Coordinate reference system of raster and cells_gdf_proj.
        cells_gdf_proj: GeoDataFrame of H3 cell polygons projected in `crs`.

    Returns:
        1D float array of mean fractions in [0.0, 1.0].
    """
    height, width = raster.shape

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
        tmp_path = f.name

    try:
        with rasterio.open(
            tmp_path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype=raster.dtype,
            crs=crs,
            transform=transform,
        ) as dst:
            dst.write(raster, 1)

        stats = exactextract.exact_extract(
            tmp_path,
            cells_gdf_proj,
            ["mean"],
            output="pandas",
        )
        return stats["mean"].fillna(0.0).to_numpy(dtype=float)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def build_ndem_reference_dataset(
    cells_gdf: gpd.GeoDataFrame,
    ndem_path: str | Path,
    bbox_wgs84: tuple[float, float, float, float] | None = None,
    processing_crs: str = "EPSG:32645",
    pre2015_cutoff: int = 2014,
    flood_fraction_threshold: float = 0.10,
    res: float = 20.0,
) -> pd.DataFrame:
    """Extract comprehensive NDEM reference metrics aligned to model H3 cells.

    Produces:
    - ref_flood_fraction_all: Union ever-flooded fraction across all years.
    - ref_flood_fraction_pre2015: Non-circular ever-flooded fraction (<= 2014).
    - years_flooded: Count of years with flood fraction >= threshold.
    - years_with_coverage: Number of annual layers covering the cell. The NDEM yearly
      aggregates are state-wide annual composites, so every cell is treated as observed
      in every year present in the product (a footprint built from flood-only polygons
      would be circular: unflooded land would read as "not imaged").
    - ref_flood_fraction_<year>: Per-year inundated fraction, for the per-year table.
    - ref_flood_frequency: True normalized frequency (years_flooded / years_with_coverage).
    - ref_ever_flooded: Binary label at threshold.
    - ref_recurrence_3yr: Binary label for recurrence >= 3 years.

    Args:
        cells_gdf: GeoDataFrame containing H3 cells.
        ndem_path: Path to NDEM historical parquet file.
        bbox_wgs84: Optional bounding box for spatial clipping.
        processing_crs: Metric CRS for zonal calculation.
        pre2015_cutoff: Cutoff year for non-circular pre-2015 subset.
        flood_fraction_threshold: Threshold to count a cell as flooded in a given year.
        res: Rasterization resolution in meters.

    Returns:
        DataFrame with H3 cell IDs and all reference target columns.
    """
    # 1. Project cells to metric CRS
    if cells_gdf.crs is None or str(cells_gdf.crs).lower() != processing_crs.lower():
        cells_proj = cells_gdf.to_crs(processing_crs)
    else:
        cells_proj = cells_gdf.copy()

    bounds = tuple(cells_proj.total_bounds)

    # 2. Load NDEM polygons (filtered gridcode != 0)
    gdf_ndem = load_ndem_polygons(ndem_path, bbox_wgs84=bbox_wgs84, filter_gridcode=True)

    # 3. Overall ever-flooded raster
    raster_all, trans_all = rasterize_flood_polygons(
        gdf_ndem, bounds=bounds, res=res, target_crs=processing_crs
    )
    frac_all = extract_zonal_fractions_from_raster(
        raster_all, trans_all, processing_crs, cells_proj
    )

    # 4. Pre-2015 non-circular subset
    if "year" in gdf_ndem.columns:
        gdf_pre = gdf_ndem[gdf_ndem["year"].astype(int) <= pre2015_cutoff]
    else:
        gdf_pre = gdf_ndem

    raster_pre, trans_pre = rasterize_flood_polygons(
        gdf_pre, bounds=bounds, res=res, target_crs=processing_crs
    )
    frac_pre = extract_zonal_fractions_from_raster(
        raster_pre, trans_pre, processing_crs, cells_proj
    )

    # 5. Multi-year frequency calculation
    years = sorted(gdf_ndem["year"].unique()) if "year" in gdf_ndem.columns else []
    n_cells = len(cells_proj)

    years_flooded_arr = np.zeros(n_cells, dtype=int)
    years_coverage_arr = np.zeros(n_cells, dtype=int)

    per_year_fracs: dict[str, np.ndarray] = {}
    for yr in years:
        sub_yr = gdf_ndem[gdf_ndem["year"] == yr]
        if sub_yr.empty:
            continue

        r_yr, t_yr = rasterize_flood_polygons(
            sub_yr, bounds=bounds, res=res, target_crs=processing_crs
        )
        frac_yr = extract_zonal_fractions_from_raster(
            r_yr, t_yr, processing_crs, cells_proj
        )

        per_year_fracs[f"ref_flood_fraction_{int(yr)}"] = frac_yr

        # Annual state-wide composite: every cell in the AOI is covered in year yr
        years_coverage_arr += 1
        is_flooded_yr = (frac_yr >= flood_fraction_threshold).astype(int)
        years_flooded_arr += is_flooded_yr

    # True normalized frequency
    freq_arr = np.where(
        years_coverage_arr > 0,
        years_flooded_arr / np.maximum(years_coverage_arr, 1),
        0.0,
    )

    h3_col = "h3_hex" if "h3_hex" in cells_gdf.columns else "h3_index"

    out_df = pd.DataFrame({
        h3_col: cells_gdf[h3_col].values if h3_col in cells_gdf.columns else np.arange(n_cells),
        "ref_flood_fraction_all": frac_all,
        "ref_flood_fraction_pre2015": frac_pre,
        "years_flooded": years_flooded_arr,
        "years_with_coverage": years_coverage_arr,
        "ref_flood_frequency": freq_arr,
        "ref_ever_flooded": (frac_all >= flood_fraction_threshold).astype(int),
        "ref_recurrence_3yr": (years_flooded_arr >= 3).astype(int),
        **per_year_fracs,
    })

    return out_df
