"""NDEM spatial agreement runner and diagnostics for riverine flood validation.

Executes the NDEM track of FLOOD_VALIDATION_PLAN.md with the Phase 0–2 integrity fixes:
1. Headline metrics on the hazard regimes NDEM actually maps (floodplain by default);
   char belt and active channel are reported per regime, never silently dropped.
2. Every predictor (model and baselines) gets ROC-AUC, PR-AUC, Spearman and a
   spatial block-bootstrap CI, plus a paired CI for "model minus baseline".
3. Per-year agreement table across every NDEM year, flagging the SAR stack year as
   in-sample and later years as temporal holdouts.
4. The 2020 event layer is scored only inside its observation footprint.
5. Class-imbalance summary with an explicit low-negative-count warning.
6. Reference provenance (gridcode audit, footprint parameters, river data files).
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple
import exactextract
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from shapely.geometry import Polygon

from ..districts import get_district
from ..susceptibility import HAZARD_REGIMES, classify_hazard_regime
from .alignment import assign_regional_split, build_alignment_dataset
from .baselines import attach_all_baselines, compute_frequency_baseline
from .config import ValidationConfig
from .metrics import (
    compute_imbalance_summary,
    compute_paired_block_bootstrap,
    compute_pr_auc_with_prevalence,
    compute_region_breakdown,
    compute_roc_auc,
    compute_spearman,
    compute_tercile_breakdown,
    compute_threshold_classification,
)
from .reference_ndem import (
    build_ndem_reference_dataset,
    extract_zonal_fractions_from_raster,
    load_ndem_polygons,
    rasterize_flood_polygons,
)
from .reference_losses import evaluate_district_loss_context
from .report import save_validation_report
from .footprints import audit_gridcode_semantics, build_reference_footprint, cells_in_footprint
from ..rivers import (
    RiverNetworkConfig,
    classify_river_network,
    compute_cell_river_distances,
    load_hydrorivers_reaches,
    load_osm_rivers_from_pbf,
)


# Predictor name -> score column on the evaluated frame. Distance baselines are
# inverted (closer = higher score) by `attach_all_baselines`.
PREDICTOR_COLUMNS: dict[str, str] = {
    "model": "susceptibility",
    "hand_only": "baseline_hand",
    "frequency_only": "baseline_freq",
    "anomalous_frequency_only": "baseline_anomalous_freq",
    "dist_mainstem": "baseline_dist_mainstem",
    "dist_tributary": "baseline_dist_tributary",
    "dist_any_river": "baseline_dist_any_river",
    "distance_to_river": "baseline_distance_to_river",
    "random": "baseline_random",
}

# Predictors carried into the per-year table (kept short so the table stays readable).
PER_YEAR_PREDICTORS = (
    "model", "hand_only", "frequency_only", "anomalous_frequency_only", "dist_mainstem", "dist_tributary",
)

FOOTPRINT_2020 = {"method": "concave_hull", "ratio": 0.3, "buffer_m": 2000.0, "min_overlap": 0.5}


def _num(value: float | None) -> float | None:
    """JSON-safe float: NaN becomes None so missing values are never reported as 0."""
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


def _score_predictors(
    df: pd.DataFrame, y_col: str, ref_col: str | None, predictors: dict[str, str]
) -> dict[str, dict[str, float | None]]:
    """ROC-AUC, PR-AUC and Spearman for every predictor present on ``df``."""
    y = df[y_col].to_numpy()
    out: dict[str, dict[str, float | None]] = {"auc": {}, "pr_auc": {}, "spearman": {}}
    for name, col in predictors.items():
        if col not in df.columns or df[col].isna().all():
            continue
        s = df[col].to_numpy(dtype=float)
        out["auc"][name] = _num(compute_roc_auc(y, s))
        out["pr_auc"][name] = _num(compute_pr_auc_with_prevalence(y, s)["pr_auc"])
        if ref_col is not None and name != "random":
            out["spearman"][name] = _num(compute_spearman(df[ref_col].to_numpy(dtype=float), s)["rho"])
    return out


def _file_provenance(path: str | Path) -> dict[str, Any]:
    """Size, SHA-256 and modification time of a reference input, so a run can be reproduced."""
    p = Path(path)
    if not p.exists():
        return {"path": str(path), "status": "missing"}
    digest = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    stat = p.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "sha256": digest.hexdigest(),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _resolve_hazard_regime(cells: pd.DataFrame) -> pd.Series:
    """Hazard regime from the model parquet, or derived from the same inputs the pipeline uses."""
    if "hazard_regime" in cells.columns and cells["hazard_regime"].notna().any():
        return cells["hazard_regime"]
    if "jrc_occurrence_mean" in cells.columns and "mean_inundation_frequency" in cells.columns:
        return pd.Series(
            classify_hazard_regime(
                jrc_occurrence_frac=cells["jrc_occurrence_mean"].to_numpy(dtype=float),
                sar_frequency=cells["mean_inundation_frequency"].to_numpy(dtype=float),
            ),
            index=cells.index,
        )
    return pd.Series([None] * len(cells), index=cells.index, dtype=object)


def _year_role(year: int, stack_year: int) -> str:
    if year == stack_year:
        return "in_sample"
    if year > stack_year:
        return "temporal_holdout"
    if year < 2015:
        return "pre_sentinel1"
    return "independent"


def _per_year_table(
    eval_df: pd.DataFrame,
    years: list[int],
    config: ValidationConfig,
) -> list[dict[str, Any]]:
    """Agreement for each NDEM year on the headline evaluation cells."""
    predictors = {k: PREDICTOR_COLUMNS[k] for k in PER_YEAR_PREDICTORS}
    rows: list[dict[str, Any]] = []
    for yr in years:
        frac_col = f"ref_flood_fraction_{yr}"
        if frac_col not in eval_df.columns:
            continue
        cov_col = f"cov_{yr}"
        mask = eval_df[cov_col].to_numpy(dtype=bool) if cov_col in eval_df.columns else np.ones(len(eval_df), bool)
        sub = eval_df.loc[mask].copy()
        sub["y_year"] = (sub[frac_col] >= config.primary_flood_fraction_threshold).astype(int)
        imbalance = compute_imbalance_summary(sub["y_year"].to_numpy())
        scores = _score_predictors(sub, "y_year", None, predictors)
        boot = compute_paired_block_bootstrap(
            sub, "y_year", frac_col, {"model": PREDICTOR_COLUMNS["model"]}, "parent_block",
            n_bootstraps=config.bootstrap_iterations, ci=config.bootstrap_ci, random_seed=config.random_seed,
        )
        rows.append({
            "year": int(yr),
            "role": _year_role(int(yr), config.sar_stack_year),
            "source": "event_layer" if cov_col in eval_df.columns else "annual_composite",
            "n_cells": imbalance["n_cells"],
            "n_pos": imbalance["n_pos"],
            "n_neg": imbalance["n_neg"],
            "prevalence": _num(imbalance["prevalence"]),
            "auc": scores["auc"],
            "auc_model_ci95": boot["auc"].get("model"),
        })
    return rows


def _regime_table(
    product: pd.DataFrame,
    domain: pd.DataFrame,
    eval_regimes: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Per-regime product footprint (all cells) next to agreement on evaluable cells.

    ``cell_count`` / ``population`` describe every published cell in the regime;
    ``eval_cell_count`` and the agreement columns describe the subset that passed the
    quality and permanent-water filters. The floodplain row's agreement equals the
    headline when ``eval_regimes == ("floodplain",)``.
    """
    total = max(len(product), 1)
    rows: list[dict[str, Any]] = []
    for reg in HAZARD_REGIMES:
        prod = product[product["hazard_regime"] == reg]
        if prod.empty:
            continue
        ev = domain[domain["hazard_regime"] == reg]
        imbalance = compute_imbalance_summary(ev["y_true_binary"].to_numpy()) if len(ev) else None
        auc = compute_roc_auc(ev["y_true_binary"].to_numpy(), ev["susceptibility"].to_numpy()) if len(ev) else math.nan
        rho = (
            compute_spearman(ev["ref_flood_frequency"].to_numpy(), ev["susceptibility"].to_numpy())["rho"]
            if len(ev) else math.nan
        )
        rows.append({
            "regime": reg,
            "in_headline": reg in eval_regimes,
            "cell_count": int(len(prod)),
            "share_pct": round(len(prod) / total * 100, 1),
            "population": round(float(prod["population"].sum()), 0) if "population" in prod.columns else None,
            "mean_susceptibility": round(float(prod["susceptibility"].mean()), 4),
            "mean_confidence": round(float(prod["confidence"].mean()), 4) if "confidence" in prod.columns else None,
            "eval_cell_count": int(len(ev)),
            "eval_n_neg": imbalance["n_neg"] if imbalance else 0,
            "ndem_prevalence": round(float(ev["y_true_binary"].mean()), 4) if len(ev) else None,
            "roc_auc": _num(auc),
            "spearman": _num(rho),
        })
    return rows


def _ndem_audit(ndem_path: Path, bbox: tuple[float, ...], processing_crs: str) -> dict[str, Any]:
    """Polygon counts and areas per year and gridcode inside the district bbox."""
    raw = load_ndem_polygons(ndem_path, bbox_wgs84=bbox, filter_gridcode=False)
    if raw.empty:
        return {"n_polygons": 0, "by_year": {}}
    proj = raw.to_crs(processing_crs)
    proj["area_km2"] = proj.geometry.area / 1e6
    if "gridcode" in proj.columns:
        proj["gridcode_key"] = proj["gridcode"].map(lambda v: "NaN" if pd.isna(v) else str(float(v)))
    elif "grid_code" in proj.columns:
        proj["gridcode_key"] = proj["grid_code"].map(lambda v: "NaN" if pd.isna(v) else str(float(v)))
    else:
        proj["gridcode_key"] = "1.0"
    if "year" not in proj.columns:
        if "from_time" in proj.columns:
            proj["year"] = pd.to_datetime(proj["from_time"], dayfirst=True, errors="coerce").dt.year.fillna(2021).astype(int)
        else:
            proj["year"] = 2021
    by_year: dict[str, Any] = {}
    for yr, grp in proj.groupby("year"):
        by_year[str(int(yr))] = {
            k: {"n": int(len(g)), "area_km2": round(float(g["area_km2"].sum()), 2)}
            for k, g in grp.groupby("gridcode_key")
        }
    return {
        "n_polygons": int(len(raw)),
        "n_flood_polygons": int((proj["gridcode_key"] != "0.0").sum()),
        "background_gridcode": "0.0 (dropped; present in 2011–2013 only)",
        "by_year": by_year,
    }


def run_ndem_validation(
    config: ValidationConfig,
) -> Tuple[dict[str, Any], pd.DataFrame]:
    """Execute complete NDEM spatial validation and diagnostics for a district.

    Args:
        config: ValidationConfig instance.

    Returns:
        Tuple of (metrics_payload_dict, evaluated_aligned_cells_df).
    """
    district_info = get_district(config.district)
    print("=" * 70)
    print(f"SETU-DRR FLOOD VALIDATION — {district_info.name.upper()} ({district_info.state})")
    print(f"Model: {config.model_version} vs Reference: ISRO NDEM")
    print("=" * 70)

    # 1. Load model cells
    print("\n[1/6] Loading model H3 cells...")
    cells_path = Path(config.processed_cells_path)
    if not cells_path.exists():
        raise FileNotFoundError(f"Model cells parquet not found at: {cells_path}")

    df_cells = pd.read_parquet(cells_path)
    print(f"  Loaded {len(df_cells)} model cells from {cells_path}")
    model_version = (
        str(df_cells["model_version"].iloc[0])
        if "model_version" in df_cells.columns and pd.notna(df_cells["model_version"].iloc[0])
        else config.model_version
    )

    h3_col = "h3_hex" if "h3_hex" in df_cells.columns else "h3_int"
    cell_polygons = [
        Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(h)])
        for h in df_cells[h3_col]
    ]
    gdf_cells = gpd.GeoDataFrame(df_cells, geometry=cell_polygons, crs="EPSG:4326")
    gdf_cells_proj = gdf_cells.to_crs(district_info.processing_crs)

    # 2. Water fractions, hazard regime, river distances
    print("\n[2/6] Resolving water masks, hazard regimes and river distances...")
    pw_str = str(config.permanent_water_raster_path or "").strip()
    if pw_str and Path(pw_str).is_file():
        stats_pw = exactextract.exact_extract(pw_str, gdf_cells_proj, ["mean"], output="pandas")
        gdf_cells_proj["permanent_water_fraction"] = stats_pw["mean"].fillna(0.0).to_numpy()
    elif "permanent_water_fraction" not in gdf_cells_proj.columns:
        print("  Notice: No permanent water raster available. Defaulting permanent_water_fraction to 0.0.")
        gdf_cells_proj["permanent_water_fraction"] = 0.0

    bw_str = str(config.baseline_water_raster_path or "").strip()
    if bw_str and Path(bw_str).is_file():
        stats_bw = exactextract.exact_extract(bw_str, gdf_cells_proj, ["mean"], output="pandas")
        gdf_cells_proj["baseline_water_fraction"] = stats_bw["mean"].fillna(0.0).to_numpy()
    elif "baseline_water_fraction" not in gdf_cells_proj.columns:
        gdf_cells_proj["baseline_water_fraction"] = 0.0

    gdf_cells_proj["hazard_regime"] = _resolve_hazard_regime(gdf_cells_proj).to_numpy()
    has_regimes = gdf_cells_proj["hazard_regime"].notna().any()
    if has_regimes:
        print(f"  Hazard regimes: {gdf_cells_proj['hazard_regime'].value_counts().to_dict()}")
    else:
        print("  Notice: no JRC occurrence in model cells — regime split unavailable; scoring all cells.")

    rivers_meta: dict[str, Any] = {"status": "not_configured"}
    pbf_path = config.osm_pbf_path
    hydro_path = config.hydrorivers_shp_path
    if pbf_path and Path(pbf_path).exists():
        print(f"  Extracting river network from {pbf_path} (OSM) and HydroRIVERS...")
        r_cfg = RiverNetworkConfig(mainstem_names=("Brahmaputra", "Brahmaputra River"))
        rivers_meta = {
            "osm_pbf": _file_provenance(pbf_path),
            "osm_licence": "ODbL 1.0 — © OpenStreetMap contributors (via Geofabrik)",
            "hydrorivers": _file_provenance(hydro_path) if hydro_path else {"status": "not_configured"},
            "hydrorivers_citation": "Lehner & Grill (2013), HydroSHEDS / HydroRIVERS v1.0",
            "mainstem_names": list(r_cfg.mainstem_names),
            "min_tributary_upstream_km2": r_cfg.min_tributary_upstream_km2,
        }
        try:
            osm_rivers = load_osm_rivers_from_pbf(
                pbf_path, district_info.bbox_wgs84, cfg=r_cfg, processing_crs=district_info.processing_crs
            )
            hydro_reaches = (
                load_hydrorivers_reaches(
                    hydro_path, district_info.bbox_wgs84, cfg=r_cfg, processing_crs=district_info.processing_crs
                )
                if hydro_path and Path(hydro_path).exists()
                else None
            )
            classified = classify_river_network(
                osm_rivers, hydrorivers=hydro_reaches, cfg=r_cfg, processing_crs=district_info.processing_crs
            )
            dists = compute_cell_river_distances(gdf_cells_proj, classified, processing_crs=district_info.processing_crs)
            for d_col in ["dist_mainstem_m", "dist_tributary_m", "dist_any_river_m"]:
                gdf_cells_proj[d_col] = dists[d_col].values
            rivers_meta["status"] = "evaluated"
            rivers_meta["river_class_counts"] = {
                str(k): int(v) for k, v in classified["river_class"].value_counts().items()
            }
        except Exception as e:  # river baselines are diagnostic; never block the core metrics
            rivers_meta["status"] = f"failed: {e}"
            print(f"  Warning: river distance extraction failed ({e}); river baselines skipped.")

    # Distance to JRC permanent water (diagnostic: circular with the JRC mask and SAR input)
    dist_raster: Path | None = (
        Path(config.distance_to_river_raster_path)
        if config.distance_to_river_raster_path and Path(config.distance_to_river_raster_path).is_file()
        else None
    )
    if dist_raster is None and pw_str and Path(pw_str).is_file():
        candidate_dist = Path(pw_str).parent / f"{district_info.key}_distance_to_river.tif"
        if not candidate_dist.is_file():
            from .baselines import generate_distance_to_water_raster
            generate_distance_to_water_raster(Path(pw_str), candidate_dist)
        dist_raster = candidate_dist
    if dist_raster is not None and dist_raster.is_file():
        stats_dist = exactextract.exact_extract(str(dist_raster), gdf_cells_proj, ["mean"], output="pandas")
        gdf_cells_proj["distance_to_river_m"] = stats_dist["mean"].to_numpy()

    # 3. NDEM reference observations
    print("\n[3/6] Ingesting and rasterizing NDEM historical flood polygons...")
    ndem_path = Path(config.ndem_yearly_aggregate_path)
    if not ndem_path.exists():
        raise FileNotFoundError(f"NDEM aggregate file not found at: {ndem_path}")

    bbox = tuple(district_info.bbox_wgs84)
    ref_df = build_ndem_reference_dataset(
        cells_gdf=gdf_cells,
        ndem_path=ndem_path,
        bbox_wgs84=bbox,
        processing_crs=district_info.processing_crs,
        pre2015_cutoff=config.pre2015_cutoff_year,
        flood_fraction_threshold=config.primary_flood_fraction_threshold,
    )
    annual_years = sorted(int(c.rsplit("_", 1)[-1]) for c in ref_df.columns if c.startswith("ref_flood_fraction_")
                          and c.rsplit("_", 1)[-1].isdigit())
    ndem_audit = _ndem_audit(ndem_path, bbox, district_info.processing_crs)
    print(f"  Reference targets for {len(ref_df)} cells; annual layers: {annual_years}")

    footprints: dict[str, Any] = {}
    event_years: list[int] = []
    year_matched_path = ndem_path.parent / f"NDEM_AS_Floods_Inundation_2020_{config.district}.parquet"
    if year_matched_path.exists():
        print("  Found 2020 event layer; building its observation footprint...")
        gdf_2020 = gpd.read_parquet(year_matched_path)
        footprint = build_reference_footprint(
            gdf_2020, district_info.processing_crs,
            buffer_m=FOOTPRINT_2020["buffer_m"], method=FOOTPRINT_2020["method"], ratio=FOOTPRINT_2020["ratio"],
        )
        in_fp = cells_in_footprint(gdf_cells_proj, footprint, min_overlap=FOOTPRINT_2020["min_overlap"])
        ref_df["cov_2020"] = in_fp
        r_2020, t_2020 = rasterize_flood_polygons(
            gdf_2020, bounds=tuple(gdf_cells_proj.total_bounds), res=20.0, target_crs=district_info.processing_crs
        )
        ref_df["ref_flood_fraction_2020"] = extract_zonal_fractions_from_raster(
            r_2020, t_2020, district_info.processing_crs, gdf_cells_proj
        )
        audit_2020 = audit_gridcode_semantics(gdf_2020)
        if {"gridcode", "from_time"} <= set(gdf_2020.columns):
            gc = gdf_2020["gridcode"].map(lambda v: "NaN" if pd.isna(v) else str(float(v)))
            per_event = gdf_2020.assign(gc=gc).groupby("from_time")["gc"].nunique()
            audit_2020["gridcode_varies_within_event"] = bool((per_event > 1).any())
        else:
            audit_2020["gridcode_varies_within_event"] = None
        audit_2020["interpretation"] = (
            "gridcode is constant within each acquisition date (NaN or 1.0 by source format); "
            "every polygon is a mapped flood extent"
            if audit_2020["gridcode_varies_within_event"] is False
            else "gridcode varies within an acquisition date — review before treating all polygons as flood"
        )
        footprints["2020"] = {
            **FOOTPRINT_2020,
            "source": year_matched_path.name,
            "cells_in_footprint": int(in_fp.sum()),
            "cells_total": int(len(in_fp)),
            "max_lat": round(float(gdf_2020.total_bounds[3]), 4),
            "gridcode_audit": audit_2020,
        }
        event_years.append(2020)
        print(f"  2020 footprint: {int(in_fp.sum())}/{len(in_fp)} cells covered")

    # 4. Alignment, evaluation domain, baselines
    print("\n[4/6] Aligning cells, applying quality / permanent-water masks, selecting evaluation domain...")
    domain_df, audit_meta = build_alignment_dataset(
        model_df=gdf_cells_proj.drop(columns=["geometry"]),
        ref_df=ref_df,
        h3_col=h3_col,
        ref_flood_fraction_col="ref_flood_fraction_all",
        water_fraction_col="permanent_water_fraction",
        max_permanent_water_fraction=config.max_permanent_water_fraction,
        required_quality_flag="full",
        primary_threshold=config.primary_flood_fraction_threshold,
        h3_block_res=config.h3_block_resolution,
    )
    domain_df = attach_all_baselines(
        domain_df,
        hand_col="mean_hand",
        freq_col="mean_inundation_frequency",
        dist_col="distance_to_river_m" if "distance_to_river_m" in domain_df.columns else None,
        random_seed=config.random_seed,
    )
    if "mean_anomalous_frequency" in domain_df.columns:
        domain_df["baseline_anomalous_freq"] = compute_frequency_baseline(domain_df["mean_anomalous_frequency"])

    eval_mask = np.ones(len(domain_df), dtype=bool)
    if has_regimes:
        eval_mask &= domain_df["hazard_regime"].isin(config.eval_regimes).to_numpy()
    if config.use_baseline_water_filter:
        eval_mask &= (domain_df["baseline_water_fraction"] <= config.max_baseline_water_fraction).to_numpy()
    eval_df = assign_regional_split(domain_df.loc[eval_mask].reset_index(drop=True))
    n_outside_domain = int((~eval_mask).sum())

    y_true = eval_df["y_true_binary"].to_numpy()
    imbalance = compute_imbalance_summary(y_true, eval_df["parent_block"].to_numpy())
    print(f"  Evaluated {imbalance['n_cells']} cells ({imbalance['n_pos']} flooded / {imbalance['n_neg']} not); "
          f"excluded non-full {audit_meta['n_excluded_non_full']}, permanent water "
          f"{audit_meta['n_excluded_permanent_water']}, outside eval regimes {n_outside_domain}")
    if imbalance["low_negative_count_warning"]:
        print(f"  WARNING: only {imbalance['n_neg']} negative cells — ROC-AUC is fragile; read the CIs.")

    # 5. Metrics
    print("\n[5/6] Computing metrics, bootstrap CIs and per-year agreement...")
    scores = _score_predictors(eval_df, "y_true_binary", "ref_flood_frequency", PREDICTOR_COLUMNS)
    boot = compute_paired_block_bootstrap(
        eval_df, "y_true_binary", "ref_flood_frequency",
        {k: v for k, v in PREDICTOR_COLUMNS.items() if k != "random"}, "parent_block",
        n_bootstraps=config.bootstrap_iterations, ci=config.bootstrap_ci, random_seed=config.random_seed,
    )
    model_ci = boot["auc"].get("model") or [None, None]
    print(f"  Model ROC-AUC {scores['auc'].get('model')} CI {model_ci}; "
          f"Spearman {scores['spearman'].get('model')}")
    for name, val in scores["auc"].items():
        if name != "model":
            print(f"    {name:<26} AUC {val}")

    flooded = eval_df[eval_df["y_true_binary"] == 1]
    sp_within_flooded = (
        _num(compute_spearman(flooded["ref_flood_frequency"].to_numpy(), flooded["susceptibility"].to_numpy())["rho"])
        if len(flooded) > 2 else None
    )

    thresholds_perf = compute_threshold_classification(
        y_true, eval_df["susceptibility"].to_numpy(), thresholds=config.decision_thresholds
    )
    terciles_perf = compute_tercile_breakdown(
        eval_df, score_col="susceptibility", y_col="y_true_binary",
        stratify_col="confidence", n_terciles=config.confidence_terciles,
    )
    regions_perf = compute_region_breakdown(
        eval_df, score_col="susceptibility", y_col="y_true_binary", region_col="region_block",
    )

    y_pre2015 = (eval_df["ref_flood_fraction_pre2015"] >= config.primary_flood_fraction_threshold).astype(int)
    auc_pre2015 = compute_roc_auc(y_pre2015.to_numpy(), eval_df["susceptibility"].to_numpy())

    per_year = _per_year_table(eval_df, sorted(set(annual_years) | set(event_years)), config)
    ym_row = next((r for r in per_year if r["year"] == 2020 and r["source"] == "event_layer"), None)
    year_matched = (
        {
            "year": 2020,
            "auc": ym_row["auc"].get("model"),
            "auc_ci95": ym_row["auc_model_ci95"],
            "auc_baselines": {k: v for k, v in ym_row["auc"].items() if k != "model"},
            "prevalence_in_footprint": ym_row["prevalence"],
            "cells_in_footprint": ym_row["n_cells"],
            "in_sample": config.sar_stack_year == 2020,
        }
        if ym_row else {}
    )

    sensitivity: dict[str, Any] = {}
    strict = eval_df[eval_df["baseline_water_fraction"] <= config.max_baseline_water_fraction]
    if len(strict) and len(np.unique(strict["y_true_binary"])) > 1:
        sensitivity["strict_baseline_water_filter"] = {
            "description": f"headline cells with JRC>=40% water covering <= {config.max_baseline_water_fraction:.0%} of the cell",
            "n_cells": int(len(strict)),
            "n_neg": int((strict["y_true_binary"] == 0).sum()),
            "auc_model": _num(compute_roc_auc(strict["y_true_binary"], strict["susceptibility"])),
        }
    if has_regimes and len(np.unique(domain_df["y_true_binary"])) > 1:
        sensitivity["all_regimes"] = {
            "description": "all quality-filtered cells regardless of hazard regime",
            "n_cells": int(len(domain_df)),
            "n_neg": int((domain_df["y_true_binary"] == 0).sum()),
            "auc_model": _num(compute_roc_auc(domain_df["y_true_binary"], domain_df["susceptibility"])),
        }

    regimes_list = (
        _regime_table(gdf_cells_proj.drop(columns=["geometry"]), domain_df, config.eval_regimes)
        if has_regimes else []
    )

    lat_corr_model, _ = spearmanr(eval_df["centroid_lat"], eval_df["susceptibility"])
    lat_corr_ref, _ = spearmanr(eval_df["centroid_lat"], eval_df["ref_flood_frequency"])

    # 6. Payload
    print("\n[6/6] Packaging and saving validation report...")
    coverage_counts = {str(yr): int(len(eval_df)) for yr in annual_years}
    if "cov_2020" in eval_df.columns:
        coverage_counts["2020"] = int(eval_df["cov_2020"].sum())

    payload: dict[str, Any] = {
        "district": config.district,
        "model_version": model_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "references": {
            "ndem": {
                "years": sorted(set(annual_years) | set(event_years)),
                "years_with_coverage": coverage_counts,
                "coverage_basis": {
                    "annual_composite": "state-wide annual composite; every evaluated cell treated as observed",
                    "event_layer": "concave-hull observation footprint (see reference_footprints)",
                },
                "polygons": ndem_audit["n_flood_polygons"] if ndem_audit.get("n_polygons") else 0,
                "gridcode_audit": ndem_audit,
                "licence": "Government Open Data License (GODL) / NRSC Data Sharing Policy",
            },
            "rivers": rivers_meta,
        },
        "reference_footprints": footprints,
        "spatial": {
            "evaluation_domain": {
                "hazard_regimes": list(config.eval_regimes) if has_regimes else None,
                "strict_baseline_water_filter": config.use_baseline_water_filter,
                "flood_fraction_threshold": config.primary_flood_fraction_threshold,
            },
            "n_cells": imbalance["n_cells"],
            "n_excluded_non_full": audit_meta["n_excluded_non_full"],
            "n_excluded_permanent_water": audit_meta["n_excluded_permanent_water"],
            "n_excluded_outside_domain": n_outside_domain,
            "prevalence": imbalance["prevalence"],
            "imbalance": imbalance,
            "spearman_frequency": scores["spearman"],
            "spearman_within_flooded_cells": sp_within_flooded,
            "auc": scores["auc"],
            "pr_auc": scores["pr_auc"],
            "ci95": {
                "auc_model": model_ci,
                "auc": boot["auc"],
                "spearman": boot["spearman"],
                "auc_model_minus": boot["auc_diff"],
                "n_blocks": boot["n_blocks"],
                "n_bootstraps": boot["n_bootstraps"],
            },
            "thresholds": thresholds_perf,
            "by_confidence_tercile": terciles_perf,
            "by_region_block": regions_perf,
            "by_regime": regimes_list,
            "per_year": per_year,
            "pre2015_subset": {"auc": _num(auc_pre2015)},
            "year_matched": year_matched,
            "sensitivity": sensitivity,
            "diagnostics": {
                "spearman_lat_vs_model": _num(lat_corr_model),
                "spearman_lat_vs_reference": _num(lat_corr_ref),
            },
        },
        # Filled by the INDOFLOODS track (checks_indofloods); NDEM never guesses it.
        "gauges": {"status": "not_evaluated", "n_stations": None, "spearman": None},
        "losses_context": evaluate_district_loss_context(config.district),
    }

    out_dir = Path(config.output_dir)
    json_path, md_path = save_validation_report(payload, output_dir=out_dir)
    cell_out = out_dir / "aligned_cells.parquet"
    domain_df.assign(in_headline=eval_mask).to_parquet(cell_out, index=False)
    print(f"  Wrote report: {md_path}")
    print(f"  Wrote metrics: {json_path}")
    print(f"  Wrote per-cell aligned parquet: {cell_out}")
    print("=" * 70)

    return payload, eval_df
