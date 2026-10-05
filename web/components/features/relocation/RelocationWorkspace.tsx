'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';

import {
  AppHeader,
  CenterPanel,
  LeftPanel,
  RightPanel,
  ThreePanelLayout,
} from '@/components/layout';
import { M3_EASE } from '@/lib/motion/m3';
import { useAllocationPlan } from '@/lib/hooks/useAllocationPlan';
import { useDistricts } from '@/lib/hooks/useDistricts';
import { useCandidateSites } from '@/lib/hooks/useCandidateSites';
import { useHabitationQueue } from '@/lib/hooks/useHabitationQueue';
import { usePrefersReducedMotion } from '@/lib/hooks/usePrefersReducedMotion';
import type {
  AllocationAssignment,
  CandidateSiteItem,
  CapacityBreakdown,
  HabitationListItem,
  HazardRegime,
} from '@/lib/api/types';

import { DistrictSelect } from './DistrictSelect';
import { RelocationHeaderMeta } from './RelocationHeaderMeta';
import { HabitationQueue } from './triage/HabitationQueue';
import { RelocationCenterPanel } from './map/RelocationCenterPanel';
import {
  AllocationControls,
  type AllocationSettings,
} from './solver/AllocationControls';
import { AllocationPanel } from './solver/AllocationPanel';
import { CapacitySimulationModal } from './solver/CapacitySimulationModal';

export interface RelocationWorkspaceProps {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  /** Solver parameters the workspace opens with. */
  initialSettings?: Partial<AllocationSettings>;
  className?: string;
}

const DEFAULT_SETTINGS: AllocationSettings = {
  maxSearchRadiusKm: 15,
  targetTier: 'immediate',
  allowGroupSplits: true,
  distancePenaltyWeight: 1,
};

/**
 * Relocation planning workspace: triage demand, inspect GIS safe havens, and solve optimal distribution.
 *
 * Orchestrated with GSAP 3 panel choreography and bi-directional focus pinging across panels.
 * All panels are fully collapsible for maximum GIS map focus.
 */
export const RelocationWorkspace = ({
  title = 'Relocation planning',
  subtitle = 'Match displaced households to candidate sites under carrying-capacity limits',
  initialSettings,
  className = '',
}: RelocationWorkspaceProps) => {
  const workspaceRef = useRef<HTMLDivElement>(null);
  const prefersReducedMotion = usePrefersReducedMotion();

  const [districtId, setDistrictId] = useState<number | null>(null);
  const [explicitSelectedHabitation, setExplicitSelectedHabitation] = useState<HabitationListItem | null>(null);
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(null);
  const [includeScreening, setIncludeScreening] = useState(false);

  // Collapsible panels state
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(false);
  const [isRightCollapsed, setIsRightCollapsed] = useState(false);

  // Auto-collapse panels on initial mount for small screens / tablets (< 1024px)
  useEffect(() => {
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      setIsLeftCollapsed(true);
      setIsRightCollapsed(true);
    }
  }, []);

  // Capacity simulation modal state
  const [simulationSite, setSimulationSite] = useState<CandidateSiteItem | null>(null);
  const [siteOverrides, setSiteOverrides] = useState<Record<number, CapacityBreakdown>>({});

  const [settings, setSettings] = useState<AllocationSettings>({
    ...DEFAULT_SETTINGS,
    ...initialSettings,
  });

  const [regimeFilter, setRegimeFilter] = useState<HazardRegime | undefined>(undefined);
  const queue = useHabitationQueue({ admin: districtId ?? undefined, regime: regimeFilter, limit: 50 });
  const { districts } = useDistricts();
  const activeDistrictId = districtId ?? districts[0]?.id ?? null;

  // Selected habitation derives first queue item as default without triggering cascading renders
  const selectedHabitation = explicitSelectedHabitation ?? queue.habitations[0] ?? null;

  const sites = useCandidateSites({
    habitationId: selectedHabitation?.id ?? null,
    radiusKm: settings.maxSearchRadiusKm,
  });

  // Merge any simulated capacity overrides
  const enhancedSites = useMemo(() => {
    return sites.sites.map((site) => {
      const override = siteOverrides[site.id];
      if (override) {
        return {
          ...site,
          capacity: override,
          allocatable: (override.cc_final ?? 0) > 0,
        };
      }
      return site;
    });
  }, [sites.sites, siteOverrides]);

  const enhancedAllocatable = useMemo(() => {
    return enhancedSites.filter((s) => s.allocatable);
  }, [enhancedSites]);

  const allocation = useAllocationPlan();

  // Phase 1: Sequential Panel Reveal on Mount
  useGSAP(
    () => {
      if (prefersReducedMotion || !workspaceRef.current) return;

      const tl = gsap.timeline();

      // Header: enters first
      tl.from('[data-panel-header]', {
        y: -8,
        opacity: 0,
        duration: 0.3,
        ease: M3_EASE.decelerate,
        clearProps: 'transform,opacity',
      });

      // Left Panel (Demand): x: -12px -> 0
      tl.from(
        '.panel-left-entrance',
        {
          x: -12,
          opacity: 0,
          duration: 0.35,
          ease: M3_EASE.decelerate,
          clearProps: 'transform,opacity',
        },
        0.05,
      );

      // Center Panel (Supply): y: 12px -> 0
      tl.from(
        '.panel-center-entrance',
        {
          y: 12,
          opacity: 0,
          duration: 0.4,
          ease: M3_EASE.decelerate,
          clearProps: 'transform,opacity',
        },
        0.12,
      );

      // Right Panel (Solver): x: 12px -> 0
      tl.from(
        '.panel-right-entrance',
        {
          x: 12,
          opacity: 0,
          duration: 0.35,
          ease: M3_EASE.decelerate,
          clearProps: 'transform,opacity',
        },
        0.18,
      );
    },
    { scope: workspaceRef, dependencies: [prefersReducedMotion] },
  );

  const handleSelectHabitation = useCallback((habitation: HabitationListItem) => {
    setExplicitSelectedHabitation(habitation);
    setSelectedSiteId(null);
  }, []);

  const handleSelectDistrict = useCallback((adminId: number) => {
    setDistrictId(adminId);
    setExplicitSelectedHabitation(null);
    setSelectedSiteId(null);
  }, []);

  const handleSolve = useCallback(() => {
    void allocation.solve({
      admin_id: activeDistrictId ?? undefined,
      max_search_radius_km: settings.maxSearchRadiusKm,
      target_tiers: [settings.targetTier],
      allow_group_splits: settings.allowGroupSplits,
      distance_penalty_weight: settings.distancePenaltyWeight,
      screening_mode: includeScreening,
    });
  }, [allocation, activeDistrictId, settings, includeScreening]);

  const handleSelectSite = useCallback(
    (site: CandidateSiteItem) =>
      setSelectedSiteId((current) => (current === site.id ? null : site.id)),
    [],
  );

  // Phase 5: Bi-directional Spatial Focus Ping
  const handleSelectAssignment = useCallback(
    (assignment: AllocationAssignment) => {
      setSelectedSiteId(assignment.site_id);

      if (!workspaceRef.current) return;

      // 1. Highlight target Candidate Site card if visible in DOM
      const siteCard = workspaceRef.current.querySelector(
        `[data-site-card][data-site-id="${assignment.site_id}"]`,
      ) as HTMLElement | null;
      if (siteCard) {
        siteCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        gsap.fromTo(
          siteCard,
          { scale: 0.98, boxShadow: '0 0 0 4px rgba(20, 184, 166, 0.6)' },
          {
            scale: 1,
            boxShadow: '0 0 0 0px rgba(20, 184, 166, 0)',
            duration: 0.65,
            ease: 'power2.out',
            clearProps: 'transform,boxShadow',
          },
        );
      }

      // 2. Flash corresponding habitation queue row
      const habRow = workspaceRef.current.querySelector(
        `[data-habitation-row][data-habitation-id="${assignment.habitation_id}"]`,
      ) as HTMLElement | null;
      if (habRow) {
        habRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        gsap.fromTo(
          habRow,
          { scale: 0.98, backgroundColor: 'rgba(20, 184, 166, 0.25)' },
          {
            scale: 1,
            backgroundColor: '',
            duration: 0.6,
            ease: 'power2.out',
            clearProps: 'transform,backgroundColor',
          },
        );
      }
    },
    [],
  );

  const handleApplyOverride = useCallback(
    (siteId: number, simulatedCapacity: CapacityBreakdown) => {
      setSiteOverrides((prev) => ({
        ...prev,
        [siteId]: simulatedCapacity,
      }));
    },
    [],
  );

  return (
    <div ref={workspaceRef} className="h-full w-full">
      <ThreePanelLayout
        className={className}
        isLeftCollapsed={isLeftCollapsed}
        onToggleLeftCollapse={() => setIsLeftCollapsed((c) => !c)}
        isRightCollapsed={isRightCollapsed}
        onToggleRightCollapse={() => setIsRightCollapsed((c) => !c)}
        header={
          <div data-panel-header>
            <AppHeader
              title={title}
              subtitle={subtitle}
              metaSlot={
                <RelocationHeaderMeta
                  totalHabitations={queue.total}
                  selectedHabitation={selectedHabitation}
                  plan={allocation.plan}
                />
              }
            />
          </div>
        }
        left={
          <LeftPanel
            title="Triage & Queue"
            onToggleCollapse={() => setIsLeftCollapsed(true)}
            className="panel-left-entrance"
          >
            <HabitationQueue
              habitations={queue.habitations}
              total={queue.total}
              isLoading={queue.isLoading}
              error={queue.error}
              selectedId={selectedHabitation?.id ?? null}
              onSelect={handleSelectHabitation}
              onRetry={queue.refetch}
              regime={regimeFilter ?? 'all'}
              onRegimeChange={setRegimeFilter}
              onToggleCollapse={() => setIsLeftCollapsed(true)}
              actionSlot={
                districts.length > 1 ? (
                  <DistrictSelect
                    options={districts}
                    value={activeDistrictId}
                    onValueChange={handleSelectDistrict}
                  />
                ) : null
              }
            />
          </LeftPanel>
        }
        center={
          <CenterPanel className="panel-center-entrance overflow-hidden">
            <RelocationCenterPanel
              habitation={selectedHabitation}
              sites={enhancedSites}
              allocatableSites={enhancedAllocatable}
              totalInRange={sites.total}
              radiusKm={settings.maxSearchRadiusKm}
              isLoadingSites={sites.isLoading}
              selectedSiteId={selectedSiteId}
              onSelectSite={handleSelectSite}
              onSimulateCapacity={(site) => setSimulationSite(site)}
              onRetrySites={sites.refetch}
              includeScreening={includeScreening}
              onIncludeScreeningChange={setIncludeScreening}
              plan={allocation.plan}
              habitations={queue.habitations}
              onSelectAssignment={handleSelectAssignment}
              isLeftCollapsed={isLeftCollapsed}
              onToggleLeftCollapse={() => setIsLeftCollapsed((c) => !c)}
              isRightCollapsed={isRightCollapsed}
              onToggleRightCollapse={() => setIsRightCollapsed((c) => !c)}
            />
          </CenterPanel>
        }
        right={
          <RightPanel
            title="Allocation & Solver"
            onToggleCollapse={() => setIsRightCollapsed(true)}
            className="panel-right-entrance"
          >
            <AllocationPanel
              plan={allocation.plan}
              isSolving={allocation.isSolving}
              error={allocation.error}
              highlightedHabitationId={selectedHabitation?.id ?? null}
              onSelectAssignment={handleSelectAssignment}
              onToggleCollapse={() => setIsRightCollapsed(true)}
              description={
                activeDistrictId
                  ? `Solving across ${districts.find((d) => d.id === activeDistrictId)?.name ?? 'the district'}`
                  : undefined
              }
              controlsSlot={
                <AllocationControls
                  settings={settings}
                  onSettingsChange={setSettings}
                  onSolve={handleSolve}
                  isSolving={allocation.isSolving}
                />
              }
            />
          </RightPanel>
        }
      />

      {/* Interactive Policy Norms Simulation Modal */}
      <CapacitySimulationModal
        site={simulationSite}
        isOpen={Boolean(simulationSite)}
        onClose={() => setSimulationSite(null)}
        onApplyOverride={handleApplyOverride}
      />
    </div>
  );
};
