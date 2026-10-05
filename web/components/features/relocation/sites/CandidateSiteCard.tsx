'use client';

import { RegimeChip } from '@/components/common/RegimeChip';
import { useRef } from 'react';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';

import { Badge } from '@/components/ui';
import { M3_DURATION, M3_EASE } from '@/lib/motion/m3';
import { usePrefersReducedMotion } from '@/lib/hooks/usePrefersReducedMotion';
import type { CandidateSiteItem } from '@/lib/api/types';

import { AugmentedCapacityCallout } from './AugmentedCapacityCallout';
import { CapacityWaterfall } from './CapacityWaterfall';
import { SiteAttributeRow } from './SiteAttributeRow';
import { SiteRejectionNotice } from './SiteRejectionNotice';
import { TENURE_LABELS, UNMEASURED_LABEL } from '../constants';

export interface CandidateSiteCardProps {
  site: CandidateSiteItem;
  rank?: number;
  isSelected?: boolean;
  onSelect?: (site: CandidateSiteItem) => void;
  /** Callback to launch policy norm capacity override simulator. */
  onSimulateCapacity?: (site: CandidateSiteItem) => void;
  /** Collapses the capacity dimension bars, for dense comparison views. */
  compact?: boolean;
  className?: string;
  classNames?: {
    root?: string;
    header?: string;
    title?: string;
    body?: string;
  };
  animation?: {
    disabled?: boolean;
    duration?: number;
  };
}

/**
 * Truncates rather than rounds, so a value that passed a `<` threshold never displays as sitting
 * on it. A site screened at MHI 0.24996 is eligible; rendering it as "0.250" against a 0.25 gate
 * reads as a violation.
 */
function truncateToPrecision(value: number, digits: number): string {
  const factor = 10 ** digits;
  return (Math.trunc(value * factor) / factor).toFixed(digits);
}

/** One candidate destination site with tactile interactions and carrying capacity reasoning. */
export const CandidateSiteCard = ({
  site,
  rank,
  isSelected = false,
  onSelect,
  onSimulateCapacity,
  compact = false,
  className = '',
  classNames = {},
  animation = {},
}: CandidateSiteCardProps) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const prefersReducedMotion = usePrefersReducedMotion();

  const { disabled: animationDisabled = false, duration = M3_DURATION.short4 } = animation;
  const animate = !animationDisabled && !prefersReducedMotion;

  useGSAP(
    () => {
      if (!animate || !rootRef.current) return;
      const element = rootRef.current;

      const toHover = (y: number) =>
        gsap.to(element, { y, duration, ease: M3_EASE.standard, overwrite: 'auto' });

      const onEnter = () => toHover(-3);
      const onLeave = () => {
        toHover(0);
        gsap.to(element, { scale: 1, duration: 0.1 });
      };
      const onDown = () => gsap.to(element, { scale: 0.985, duration: 0.08, ease: 'power1.out' });
      const onUp = () => gsap.to(element, { scale: 1, duration: 0.12, ease: 'power1.out' });

      element.addEventListener('mouseenter', onEnter);
      element.addEventListener('mouseleave', onLeave);
      element.addEventListener('pointerdown', onDown);
      element.addEventListener('pointerup', onUp);
      element.addEventListener('pointercancel', onUp);

      // Subtle pulse flash on selection change
      if (isSelected) {
        gsap.fromTo(
          element,
          { scale: 0.99 },
          { scale: 1, duration: 0.3, ease: 'back.out(2)' }
        );
      }

      return () => {
        element.removeEventListener('mouseenter', onEnter);
        element.removeEventListener('mouseleave', onLeave);
        element.removeEventListener('pointerdown', onDown);
        element.removeEventListener('pointerup', onUp);
        element.removeEventListener('pointercancel', onUp);
      };
    },
    { scope: rootRef, dependencies: [animate, duration, isSelected] },
  );

  return (
    <div
      ref={rootRef}
      data-site-card
      data-site-id={site.id}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={() => onSelect?.(site)}
      onKeyDown={(event) => {
        if (onSelect && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          onSelect(site);
        }
      }}
      className={[
        'flex flex-col gap-3 rounded-2xl border p-4 will-change-transform transition-all duration-150',
        isSelected
          ? 'border-accent bg-accent/[0.08] shadow-[0_0_14px_rgba(20,184,166,0.22)] dark:shadow-[0_0_14px_rgba(45,212,191,0.18)] ring-1 ring-accent/60'
          : 'border-line/60 bg-surface-1/40',
        site.allocatable ? '' : 'opacity-90',
        onSelect ? 'cursor-pointer hover:border-line-strong hover:bg-surface-1/60' : '',
        classNames.root ?? '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className={['flex items-start justify-between gap-3', classNames.header ?? ''].join(' ')}>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            {rank !== undefined ? (
              <span className="font-mono text-[10px] text-ink-faint">#{rank}</span>
            ) : null}
            <h3 className={['truncate text-[13px] font-semibold text-ink', classNames.title ?? ''].join(' ')}>
              Site {site.id}
            </h3>
          </div>
          <span className="text-[10px] text-ink-faint">
            {TENURE_LABELS[site.tenure] ?? site.tenure} ·{' '}
            {site.assessment_status.replace(/_/g, ' ')}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {site.hazard_regime ? <RegimeChip regime={site.hazard_regime} showLabel={false} /> : null}
          {site.suitability != null ? (
            <Badge variant="info" size="sm" title="Composite suitability score (0–100)">
              {site.suitability}/100
            </Badge>
          ) : null}
          <Badge
            variant={site.allocatable ? 'safe' : site.eligibility_status === 'unknown' ? 'warning' : 'critical'}
            size="sm"
          >
            {site.allocatable ? 'Allocatable' : site.eligibility_status}
          </Badge>
        </div>
      </div>

      <SiteAttributeRow
        items={[
          { label: 'Distance', value: `${site.distance_km.toFixed(2)} km` },
          { label: 'Area', value: `${site.area_ha.toFixed(1)} ha` },
          { label: 'Slope', value: `${site.slope_mean.toFixed(1)}°` },
          {
            label: 'MHI',
            value: site.mhi_max != null ? truncateToPrecision(site.mhi_max, 3) : UNMEASURED_LABEL,
            hint: 'Maximum static multi-hazard index inside the site',
          },
        ]}
      />

      <div className={['flex flex-col gap-3', classNames.body ?? ''].join(' ')}>
        <CapacityWaterfall
          capacity={site.capacity}
          showDimensions={!compact}
          animation={{ disabled: !animate }}
        />

        {site.allocatable ? (
          <AugmentedCapacityCallout
            augmented={site.augmented}
            baseCapacity={site.capacity.cc_final}
          />
        ) : (
          <SiteRejectionNotice
            reasons={site.rejection_reasons ?? []}
            eligibilityStatus={site.eligibility_status}
          />
        )}

        {onSimulateCapacity && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSimulateCapacity(site);
            }}
            className="mt-1 flex w-full items-center justify-center gap-1.5 rounded-xl border border-accent/40 bg-accent/10 py-2 text-[11px] font-semibold text-accent hover:bg-accent/20 hover:border-accent transition-all active:scale-[0.98] cursor-pointer"
          >
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth="2"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"
              />
            </svg>
            <span>Simulate Capacity Overrides</span>
          </button>
        )}
      </div>
    </div>
  );
};
