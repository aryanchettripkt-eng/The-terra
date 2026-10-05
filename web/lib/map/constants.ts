/** Map defaults, palettes and hazard metadata shared across the map feature. */

import type { CoverageFlag, HazardRegime, HazardType, RelocationPathway } from '@/lib/api/types';

export type RGBAColor = [number, number, number, number];

/** Barpeta pilot AOI — mirrors `pipeline/hazard/flood/aoi.py:BARPETA_BBOX_WGS84`. */
export const BARPETA_BBOX: [number, number, number, number] = [90.7, 26.05, 91.45, 26.75];

export const BARPETA_LGD_CODE = 277;

export const DEFAULT_VIEW_STATE = {
  longitude: (BARPETA_BBOX[0] + BARPETA_BBOX[2]) / 2,
  latitude: (BARPETA_BBOX[1] + BARPETA_BBOX[3]) / 2,
  zoom: 9.2,
  pitch: 0,
  bearing: 0,
} as const;

/**
 * Sequential ramp for classed susceptibility, dark-ground safe.
 * Seven stops for the six quantile breaks the API returns.
 */
export const SUSCEPTIBILITY_RAMP: RGBAColor[] = [
  [22, 122, 139, 255], // Deep Teal / Blue (#167a8b)
  [82, 153, 119, 255], // Sage / Forest Green (#529977)
  [216, 186, 86, 255], // Sand Yellow / Warm Amber (#d8ba56)
  [215, 120, 57, 255], // Terracotta / Coral Orange (#d77839)
  [197, 70, 49, 255],  // Brick Red / Crimson (#c54631)
];

/**
 * Amber/orange/vermilion ramp specifically for active char-belt (fluvial erosion) cells.
 * Visually distinguishes char dynamics from terrestrial floodplain inundation.
 */
export const CHAR_BELT_RAMP: RGBAColor[] = [
  [217, 119, 6, 255],  // Amber-600
  [234, 88, 12, 255],  // Orange-600
  [225, 29, 72, 255],  // Rose-600
  [190, 18, 60, 255],  // Rose-700
  [136, 19, 55, 255],  // Rose-900
];

/**
 * Cells that are in the active perennial river channel.
 * Visually differentiated: cool slate/blue-grey with distinctive cyan outline,
 * keeping the river channel visible without conflating with terrestrial land.
 */
export const CHANNEL_COLOR: RGBAColor = [30, 58, 88, 200];
export const CHANNEL_OUTLINE_COLOR: RGBAColor = [56, 189, 248, 220]; // Sky-400

/**
 * Cells that are safe *by construction* (FR-3.17 hard-zero: HAND > 30 m or slope > 15°).
 * Deliberately off-ramp so a structurally safe cell never reads as "low measured risk".
 */
export const HARD_ZERO_COLOR: RGBAColor = [72, 84, 92, 190];

/** Unobserved cells are drawn as an outline only — never filled, never green. */
export const NO_COVERAGE_OUTLINE_COLOR: RGBAColor = [148, 163, 184, 220];

export const SELECTED_OUTLINE_COLOR: RGBAColor = [255, 255, 255, 255];

export const HOVER_OUTLINE_COLOR: RGBAColor = [226, 232, 240, 200];

/** Hatch overlay marking cells whose normalised confidence falls below the threshold. */
export const LOW_CONFIDENCE_HATCH_COLOR: RGBAColor = [12, 16, 24, 205];

/**
 * Forecast Alert Zone overlay.
 *
 * Two distinct treatments, because `mhi_fcst` falls back to the static hazard floor when a
 * cell carries no forecast trigger. Painting both the same would let a cycle in which the
 * weather model moved nothing read as a live forecast alert.
 */
export const FORECAST_DRIVEN_FILL_COLOR: RGBAColor = [244, 114, 22, 165];
export const FORECAST_DRIVEN_OUTLINE_COLOR: RGBAColor = [251, 146, 60, 255];

/** Cells listed at their static baseline: outline only, deliberately unfilled. */
export const FORECAST_BASELINE_OUTLINE_COLOR: RGBAColor = [125, 211, 252, 190];

export const COVERAGE_LABELS: Record<CoverageFlag, string> = {
  full: 'Measured',
  low_coverage: 'Partial coverage',
  no_coverage: 'No data',
  channel_excluded: 'River channel',
};

export const COVERAGE_DESCRIPTIONS: Record<CoverageFlag, string> = {
  full: 'At least half the cell area carries valid raster pixels.',
  low_coverage: 'Under half the cell was observed; the score is directional only.',
  no_coverage: 'No valid pixels. The 0.00 score is a fill, not a measurement.',
  channel_excluded:
    'Active river channel, not land. Excluded from scoring; the 0.00 shown is a placeholder, not a safe reading.',
};

export const HAZARD_LABELS: Record<HazardType, string> = {
  landslide: 'Landslide',
  flash_flood: 'Flash flood',
  storm_surge: 'Storm surge',
  riverine_flood: 'Riverine flood',
  coastal_erosion: 'Coastal erosion',
  cloudburst: 'Cloudburst',
};

export const REGIME_ORDER: readonly HazardRegime[] = ['floodplain', 'char_belt', 'channel'];

export type RegimeVisibility = Record<HazardRegime, boolean>;

export const DEFAULT_REGIME_VISIBILITY: RegimeVisibility = {
  floodplain: true,
  char_belt: true,
  channel: true,
};

export const REGIME_LABELS: Record<HazardRegime, string> = {
  floodplain: 'Floodplain',
  char_belt: 'Char belt',
  channel: 'River channel',
};

/** Material Symbols icon per regime. */
export const REGIME_ICONS: Record<HazardRegime, string> = {
  floodplain: 'landscape',
  char_belt: 'waves',
  channel: 'water',
};

export const REGIME_DESCRIPTIONS: Record<HazardRegime, string> = {
  floodplain: 'Inland terrestrial alluvial plain subject to backwater and embankment-breach inundation.',
  char_belt: 'Dynamic Brahmaputra sandbar island facing high lateral erosion and seasonal submersion.',
  channel: 'Perennial active riverbed. Not land: excluded from scoring and from risk statistics.',
};

/** Dashed outline drawn around the char-belt corridor. */
export const CHAR_BELT_BOUNDARY_COLOR: RGBAColor = [251, 191, 36, 255]; // Amber-400
export const CHAR_BELT_BOUNDARY_DASH: [number, number] = [6, 4];

/** H3 resolutions the map offers. Source data is res 8; 7 and 6 are client-side roll-ups. */
export const SUPPORTED_RESOLUTIONS = [6, 7, 8] as const;

export type SupportedResolution = (typeof SUPPORTED_RESOLUTIONS)[number];

export const SOURCE_RESOLUTION = 8;

/**
 * Default cut for the low-confidence hatch, applied to *normalised* confidence.
 * On the Barpeta flood layer raw confidence peaks at 0.167 (10 SAR scenes against a
 * 30-observation ceiling), so an absolute cut of 0.3 would hatch every cell on the map.
 */
export const DEFAULT_CONFIDENCE_HATCH_THRESHOLD = 0.5;

export const MAP_ATTRIBUTION =
  'Map © OpenFreeMap, OpenStreetMap contributors · Copernicus Sentinel-1 · ASF GLO-30 HAND · JRC GSW · ESA WorldCover';

/**
 * Score formula shown on the dossier per regime. Keep in step with `susceptibility.py`
 * (`DEFAULT_FLOODPLAIN_WEIGHTS`, `DEFAULT_CHAR_WEIGHTS`).
 */
export const REGIME_FORMULAS: Record<HazardRegime, string> = {
  floodplain: 'S = 0.35·HAND + 0.35·F_anom + 0.30·D_tributary',
  char_belt: 'S = 0.40·instability + 0.30·JRC occurrence + 0.30·D_mainstem',
  channel: 'Not scored — river channel',
};

/** Formula for cells with no regime (older builds without a JRC layer). */
export const LEGACY_FLOOD_FORMULA = 'S_f = 0.5·F + 0.5·(1 − HAND/P99)';

/** Distance at which river proximity stops contributing to the score (metres). */
export const TRIBUTARY_DISTANCE_SCALE_M = 5000;
export const MAINSTEM_DISTANCE_SCALE_M = 10000;

/** What each regime's relocation pathway means, in officer-facing words. */
export const PATHWAY_LABELS: Record<RelocationPathway, string> = {
  mainland_resettlement: 'Mainland resettlement',
  in_situ_or_nearby: 'In-situ mitigation or nearby site',
  not_applicable: 'No regime pathway',
};
