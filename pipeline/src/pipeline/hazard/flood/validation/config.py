"""Validation configuration and district-specific parameters.

Defines thresholds, resolutions, reference data paths, and evaluation
rules for the flood susceptibility validation framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ..districts import DISTRICTS, DistrictConfig, get_district


@dataclass(frozen=True)
class ValidationConfig:
    """Configuration for validating flood susceptibility in a district."""

    district: str
    """District key slug (e.g. 'barpeta', 'dholpur', 'morena')."""

    model_version: str = "flood-susceptibility-v0.2"
    """Model version evaluated."""

    # Primary flood fraction target at H3 cell level (NDEM inundated fraction >= threshold)
    primary_flood_fraction_threshold: float = 0.10

    # Sensitivity thresholds for binary target
    flood_fraction_sensitivities: tuple[float, ...] = (0.05, 0.10, 0.25)

    # Multi-year recurrence target (flooded in at least N years)
    stricter_years_threshold: int = 3

    # Classification decision thresholds evaluated for precision/recall/F1
    decision_thresholds: tuple[float, ...] = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)

    # Permanent water mask: exclude cells where permanent water fraction exceeds this threshold
    max_permanent_water_fraction: float = 0.01

    # Headline evaluation domain (Phase 2): hazard regimes scored against NDEM. NDEM maps
    # terrestrial flood damage, so char belts and active channel are reported in the
    # per-regime table but not mixed into the headline numbers.
    eval_regimes: tuple[str, ...] = ("floodplain",)

    # Seasonal baseline water mask (Priority 1). No longer the headline filter; reported
    # as a sensitivity row. Setting use_baseline_water_filter re-applies it to the headline.
    max_baseline_water_fraction: float = 0.01
    use_baseline_water_filter: bool = False

    # Year of the Sentinel-1 stack the model is built from. Reference years equal to it
    # are in-sample; later years are temporal holdouts.
    sar_stack_year: int = 2020

    # Sensitivity variations for permanent water masking (e.g. 1% and 5%)
    permanent_water_sensitivities: tuple[float, ...] = (0.01, 0.05)

    # Cutoff year for pre-2015 non-circular comparison (years <= 2014)
    pre2015_cutoff_year: int = 2014

    # Spatial resolutions
    h3_eval_resolution: int = 8
    h3_block_resolution: int = 5  # For spatial block bootstrapping

    # Bootstrap parameters
    bootstrap_iterations: int = 500
    bootstrap_ci: float = 0.95
    random_seed: int = 42

    # Confidence stratification
    confidence_terciles: int = 3

    # Paths
    processed_cells_path: str = ""
    ndem_yearly_aggregate_path: str = ""
    ndem_per_event_path: str = ""
    permanent_water_raster_path: str = ""
    baseline_water_raster_path: str = ""
    distance_to_river_raster_path: str = ""
    osm_pbf_path: str = ""
    hydrorivers_shp_path: str = ""
    output_dir: str = ""



# District-specific defaults for reference filenames and paths
DISTRICT_VALIDATION_DEFAULTS: dict[str, dict[str, str]] = {
    "barpeta": {
        "processed_cells_path": "data/processed/flood/barpeta/flood_susceptibility_h3_res8.parquet",
        "ndem_yearly_aggregate_path": "data/validation/ndem/NDEM_AS_Yearly_Aggregate_Flood_Innundation_1998_to_2013_2021.parquet",
        "ndem_per_event_path": "data/validation/ndem/NDEM_AS_Floods_Inundation.parquet",
        "permanent_water_raster_path": "data/interim/flood_districts/barpeta/barpeta_jrc_permanent_water.tif",
        "baseline_water_raster_path": "data/interim/flood_districts/barpeta/barpeta_jrc_baseline_water.tif",
        "distance_to_river_raster_path": "data/interim/flood_districts/barpeta/barpeta_distance_to_river.tif",
        "osm_pbf_path": "data/raw/osm/north-eastern-zone-latest.osm.pbf",
        "hydrorivers_shp_path": "data/raw/hydrorivers/HydroRIVERS_v10_as_shp/HydroRIVERS_v10_as.shp",
        "output_dir": "data/processed/flood_validation/barpeta",
    },

    "dholpur": {
        "processed_cells_path": "data/processed/flood/dholpur/flood_susceptibility_h3_res8.parquet",
        "ndem_yearly_aggregate_path": "data/validation/ndem/NDEM_RJ_Floods_Inundation.parquet",
        "ndem_per_event_path": "",
        "permanent_water_raster_path": "data/interim/flood_districts/dholpur/dholpur_jrc_permanent_water.tif",
        "baseline_water_raster_path": "data/interim/flood_districts/dholpur/dholpur_jrc_baseline_water.tif",
        "output_dir": "data/processed/flood_validation/dholpur",
    },
    "morena": {
        "processed_cells_path": "data/processed/flood/morena/flood_susceptibility_h3_res8.parquet",
        "ndem_yearly_aggregate_path": "data/validation/ndem/NDEM_MP_Floods_Inundation.parquet",
        "ndem_per_event_path": "",
        "permanent_water_raster_path": "data/interim/flood_districts/morena/morena_jrc_permanent_water.tif",
        "baseline_water_raster_path": "data/interim/flood_districts/morena/morena_jrc_baseline_water.tif",
        "output_dir": "data/processed/flood_validation/morena",
    },
    "wayanad": {
        "processed_cells_path": "data/processed/flood/wayanad/flood_susceptibility_h3_res8.parquet",
        "ndem_yearly_aggregate_path": "",
        "ndem_per_event_path": "",
        "permanent_water_raster_path": "data/interim/flood_districts/wayanad/wayanad_jrc_permanent_water.tif",
        "baseline_water_raster_path": "data/interim/flood_districts/wayanad/wayanad_jrc_baseline_water.tif",
        "output_dir": "data/processed/flood_validation/wayanad",
    },
}


def get_validation_config(
    district: str,
    *,
    max_permanent_water_fraction: float | None = None,
    max_baseline_water_fraction: float | None = None,
    use_baseline_water_filter: bool | None = None,
    primary_flood_fraction_threshold: float | None = None,
    model_version: str | None = None,
    processed_cells_path: str | None = None,
    baseline_water_raster_path: str | None = None,
    distance_to_river_raster_path: str | None = None,
    osm_pbf_path: str | None = None,
    hydrorivers_shp_path: str | None = None,
    output_dir: str | None = None,
) -> ValidationConfig:
    """Construct a ValidationConfig for a registered district with defaults.

    Args:
        district: Slug for district (e.g. 'barpeta').
        max_permanent_water_fraction: Optional override for water mask threshold.
        max_baseline_water_fraction: Optional override for baseline water threshold.
        use_baseline_water_filter: Re-apply the strict baseline-water exclusion to the headline
            (default off; it is always reported as a sensitivity row).
        primary_flood_fraction_threshold: Optional override for flood threshold.
        model_version: Optional override for model version name.
        processed_cells_path: Optional override for model parquet path.
        baseline_water_raster_path: Optional override for baseline water GeoTIFF.
        distance_to_river_raster_path: Optional override for distance to river GeoTIFF.
        osm_pbf_path: Optional override for OSM PBF path.
        hydrorivers_shp_path: Optional override for HydroRIVERS shapefile path.
        output_dir: Optional override for output directory.

    Returns:
        Configured immutable ValidationConfig instance.
    """
    dist_config = get_district(district)
    defaults = DISTRICT_VALIDATION_DEFAULTS.get(dist_config.key, {})

    pw_thresh = (
        max_permanent_water_fraction
        if max_permanent_water_fraction is not None
        else 0.01
    )
    bw_thresh = (
        max_baseline_water_fraction
        if max_baseline_water_fraction is not None
        else 0.01
    )
    flood_thresh = (
        primary_flood_fraction_threshold
        if primary_flood_fraction_threshold is not None
        else 0.10
    )
    out_dir = output_dir or defaults.get(
        "output_dir", f"data/processed/flood_validation/{dist_config.key}"
    )
    bw_raster = baseline_water_raster_path or defaults.get("baseline_water_raster_path", "")
    dist_raster = distance_to_river_raster_path or defaults.get("distance_to_river_raster_path", "")
    pbf_file = osm_pbf_path or defaults.get("osm_pbf_path", "")
    hydro_shp = hydrorivers_shp_path or defaults.get("hydrorivers_shp_path", "")

    use_bw = bool(use_baseline_water_filter)

    return ValidationConfig(
        district=dist_config.key,
        model_version=model_version or "flood-susceptibility-v0.2",
        primary_flood_fraction_threshold=flood_thresh,
        max_permanent_water_fraction=pw_thresh,
        max_baseline_water_fraction=bw_thresh,
        use_baseline_water_filter=use_bw,
        processed_cells_path=processed_cells_path or defaults.get(
            "processed_cells_path",
            f"data/processed/flood/{dist_config.key}/flood_susceptibility_h3_res8.parquet",
        ),
        ndem_yearly_aggregate_path=defaults.get("ndem_yearly_aggregate_path", ""),
        ndem_per_event_path=defaults.get("ndem_per_event_path", ""),
        permanent_water_raster_path=defaults.get("permanent_water_raster_path", ""),
        baseline_water_raster_path=bw_raster,
        distance_to_river_raster_path=dist_raster,
        osm_pbf_path=pbf_file,
        hydrorivers_shp_path=hydro_shp,
        output_dir=out_dir,
    )


