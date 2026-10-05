'use client';

import { useRef } from 'react';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';

import { M3_DURATION, M3_EASE } from '@/lib/motion/m3';
import { RegimeChip } from '@/components/common/RegimeChip';
import { usePrefersReducedMotion } from '@/lib/hooks/usePrefersReducedMotion';
import type { AllocationAssignment } from '@/lib/api/types';
import { PATHWAY_LABELS } from '@/lib/map/constants';

import { TierBadge } from '../TierBadge';

export interface AllocationAssignmentRowProps {
  assignment: AllocationAssignment;
  isHighlighted?: boolean;
  onSelect?: (assignment: AllocationAssignment) => void;
  className?: string;
  classNames?: {
    root?: string;
    origin?: string;
    destination?: string;
    households?: string;
    split?: string;
  };
  animation?: {
    disabled?: boolean;
    duration?: number;
  };
}

/** One habitation-to-site assignment produced by the solver with tactile microinteractions. */
export const AllocationAssignmentRow = ({
  assignment,
  isHighlighted = false,
  onSelect,
  className = '',
  classNames = {},
  animation = {},
}: AllocationAssignmentRowProps) => {
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

      const onEnter = () => toHover(-2);
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

      return () => {
        element.removeEventListener('mouseenter', onEnter);
        element.removeEventListener('mouseleave', onLeave);
        element.removeEventListener('pointerdown', onDown);
        element.removeEventListener('pointerup', onUp);
        element.removeEventListener('pointercancel', onUp);
      };
    },
    { scope: rootRef, dependencies: [animate, duration] },
  );

  return (
    <div
      ref={rootRef}
      data-assignment-row
      data-site-id={assignment.site_id}
      data-habitation-name={assignment.habitation_name}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={() => onSelect?.(assignment)}
      onKeyDown={(event) => {
        if (onSelect && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          onSelect(assignment);
        }
      }}
      className={[
        'flex flex-col gap-1 rounded-xl border px-3 py-2 will-change-transform transition-all duration-150',
        isHighlighted
          ? 'border-accent bg-accent/[0.08] shadow-[0_0_12px_rgba(20,184,166,0.25)] ring-1 ring-accent/50'
          : 'border-line/60 bg-surface-1/40 hover:border-line-strong hover:bg-surface-2/40',
        onSelect ? 'cursor-pointer' : '',
        classNames.root ?? '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="flex items-center gap-2">
        <span className={['min-w-0 flex-1 truncate text-[12px] font-semibold text-ink', classNames.origin ?? ''].join(' ')}>
          {assignment.habitation_name}
        </span>
        {assignment.habitation_regime ? (
          <RegimeChip regime={assignment.habitation_regime} showLabel={false} />
        ) : null}
        <TierBadge tier={assignment.tier} />
      </div>

      <div className="flex items-center gap-2 text-[10px] text-ink-faint">
        <span aria-hidden className="text-accent font-bold">→</span>
        <span className={['truncate font-medium text-ink', classNames.destination ?? ''].join(' ')}>
          Site {assignment.site_id}
        </span>
        {assignment.relocation_pathway === 'mainland_resettlement' ? (
          <span className="truncate text-amber-700 dark:text-amber-400" title={PATHWAY_LABELS.mainland_resettlement}>
            · mainland
          </span>
        ) : null}
        <span aria-hidden>·</span>
        <span className="font-mono tabular-nums">{assignment.site_distance_km.toFixed(2)} km</span>
        {assignment.site_suitability != null ? (
          <>
            <span aria-hidden>·</span>
            <span className="font-mono tabular-nums">{assignment.site_suitability}/100</span>
          </>
        ) : null}
        <span
          className={['ml-auto font-mono font-bold tabular-nums text-ink', classNames.households ?? ''].join(' ')}
        >
          {assignment.households.toLocaleString()} HH
        </span>
      </div>

      {assignment.has_group_split && assignment.split_details ? (
        <p className={['text-[10px] leading-snug text-warning font-medium', classNames.split ?? ''].join(' ')}>
          {assignment.split_details}
        </p>
      ) : null}
    </div>
  );
};
