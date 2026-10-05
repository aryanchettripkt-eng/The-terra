/** Endpoint bindings for the relocation planning API (triage, candidate sites, allocation). */

import { apiGet, apiPost } from './client';
import type {
  AllocationPlanRequest,
  AllocationPlanResponse,
  CandidateSitePage,
  HabitationPage,
  HazardRegime,
  HabitationRiskDossier,
  SiteCapacityOverrideRequest,
  SiteCapacityOverrideResponse,
  Tier,
} from './types';

export interface FetchHabitationsParams {
  /** admin_boundary id, to scope the queue to one district. */
  admin?: number;
  tier?: Tier;
  /** Queue ordering; the API defaults to `urgency`. */
  sort?: 'urgency' | 'caseload';
  /** Flood hazard regime of the habitation's cell. */
  regime?: HazardRegime;
  limit?: number;
  offset?: number;
}

/** Prioritised habitation triage queue — the demand side of the allocation. */
export function fetchHabitations(
  params: FetchHabitationsParams = {},
  signal?: AbortSignal,
): Promise<HabitationPage> {
  const { admin, tier, sort, regime, limit = 50, offset = 0 } = params;
  return apiGet<HabitationPage>('/habitations', { admin, tier, sort, regime, limit, offset }, signal);
}

/** Full risk dossier for one habitation: vulnerability breakdown and triage rationale. */
export function fetchHabitationRisk(
  habitationId: number,
  signal?: AbortSignal,
): Promise<HabitationRiskDossier> {
  return apiGet<HabitationRiskDossier>(`/habitations/${habitationId}/risk`, undefined, signal);
}

export interface FetchCandidateSitesParams {
  /** Widens the list to sites the H7 policy rejected, each carrying its rejection reasons. */
  includeScreening?: boolean;
  /** Server-side radius filter, in km. */
  radiusKm?: number;
  minSuitability?: number;
  limit?: number;
}

/**
 * Ranked candidate relocation sites for one habitation.
 *
 * With `includeScreening`, ineligible sites are returned too — a planner needs to see that a
 * site was excluded and why, rather than have it silently vanish from the comparison.
 */
export function fetchCandidateSites(
  habitationId: number,
  params: FetchCandidateSitesParams = {},
  signal?: AbortSignal,
): Promise<CandidateSitePage> {
  const { includeScreening, radiusKm, minSuitability, limit = 50 } = params;
  return apiGet<CandidateSitePage>(
    `/habitations/${habitationId}/sites`,
    {
      include_screening: includeScreening ? 'true' : undefined,
      radius_km: radiusKm,
      min_suitability: minSuitability,
      limit,
    },
    signal,
  );
}

/**
 * Runs the min-cost-flow allocation solver and persists an `allocation_run`.
 *
 * Requires an authenticated government official — the endpoint is gated on the
 * `ALLOCATION_RUN` permission and writes a canonical, audited decision record.
 */
export function solveAllocationPlan(
  request: AllocationPlanRequest,
  signal?: AbortSignal,
): Promise<AllocationPlanResponse> {
  return apiPost<AllocationPlanResponse>('/plan/allocate', request, signal);
}

/**
 * Recomputes candidate site carrying capacity with overridden policy norms or resource inputs.
 * Simulates carrying capacity under modified policy parameters (plot area, LPCD, spare school/health seats).
 */
export function overrideSiteCapacity(
  siteId: number,
  overrides: SiteCapacityOverrideRequest,
  signal?: AbortSignal,
): Promise<SiteCapacityOverrideResponse> {
  return apiPost<SiteCapacityOverrideResponse>(`/sites/${siteId}/capacity`, overrides, signal);
}

/**
 * Fetches nearby OSM public infrastructure facilities (schools, healthcare, water points)
 * within proximity buffer of a candidate relocation site.
 */
export function fetchSiteInfrastructure(
  siteId: number,
  signal?: AbortSignal,
): Promise<import('./types').OsmFacilityItem[]> {
  return apiGet<import('./types').OsmFacilityItem[]>(`/sites/${siteId}/infrastructure`, undefined, signal);
}

export interface FetchHealthFacilitiesParams {
  admin?: number;
  facility_type?: 'sub_cen' | 'phc' | 'chc' | string;
}

/**
 * Spatial GeoJSON endpoint for primary and secondary healthcare facilities.
 * Supplementary layer indicating IPHS capacity and flood safety status.
 */
export function fetchHealthFacilities(
  params: FetchHealthFacilitiesParams = {},
  signal?: AbortSignal,
): Promise<import('./types').HealthFacilitiesGeoJSON> {
  const { admin, facility_type } = params;
  return apiGet<import('./types').HealthFacilitiesGeoJSON>(
    '/sites/facilities/health',
    { admin, facility_type },
    signal,
  );
}


