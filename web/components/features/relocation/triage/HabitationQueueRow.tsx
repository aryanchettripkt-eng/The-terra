'use client';

import { useRef } from 'react';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';

import { M3_DURATION, M3_EASE } from '@/lib/motion/m3';
import { RegimeChip } from '@/components/common/RegimeChip';
import { usePrefersReducedMotion } from '@/lib/hooks/usePrefersReducedMotion';
import type { HabitationListItem } from '@/lib/api/types';
import { formatCount, formatPercent, formatScore } from '@/lib/map/format';
import { PATHWAY_LABELS } from '@/lib/map/constants';

import { TierBadge } from '../TierBadge';

export interface HabitationQueueRowProps {
  habitation: HabitationListItem;
  rank: number;
  isSelected?: boolean;
  /** Shows the habitation's hazard regime as a chip beside its tier. */
  showRegime?: boolean;
  onSelect?: (habitation: HabitationListItem) => void;
  className?: string;
  classNames?: {
    root?: string;
    rank?: string;
    name?: string;
    meta?: string;
    score?: string;
  };
  animation?: {
    disabled?: boolean;
    duration?: number;
  };
}

/** One habitation in the triage queue with tactile feedback and tier breathing. */
export const HabitationQueueRow = ({
  habitation,
  rank,
  isSelected = false,
  showRegime = true,
  onSelect,
  className = '',
  classNames = {},
  animation = {},
}: HabitationQueueRowProps) => {
  const rootRef = useRef<HTMLButtonElement>(null);
  const prefersReducedMotion = usePrefersReducedMotion();

  const { disabled: animationDisabled = false, duration = M3_DURATION.short4 } = animation;
  const animate = !animationDisabled && !prefersReducedMotion;
  const isImmediate = habitation.tier === 'immediate';

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

      // Low frequency breathing for critical / immediate urgency
      if (isImmediate) {
        gsap.to('[data-tier-breathing]', {
          opacity: 0.8,
          scale: 0.98,
          duration: 1.5,
          repeat: -1,
          yoyo: true,
          ease: 'sine.inOut',
        });
      }

      return () => {
        element.removeEventListener('mouseenter', onEnter);
        element.removeEventListener('mouseleave', onLeave);
        element.removeEventListener('pointerdown', onDown);
        element.removeEventListener('pointerup', onUp);
        element.removeEventListener('pointercancel', onUp);
      };
    },
    { scope: rootRef, dependencies: [animate, duration, isImmediate] },
  );

  return (
    <button
      ref={rootRef}
      type="button"
      data-habitation-row
      data-habitation-id={habitation.id}
      onClick={() => onSelect?.(habitation)}
      aria-pressed={isSelected}
      className={[
        'flex w-full flex-col gap-1.5 rounded-xl border px-3 py-2.5 text-left will-change-transform',
        'transition-colors duration-150 cursor-pointer',
        isSelected
          ? 'border-accent bg-accent/10 shadow-[0_0_12px_rgba(20,184,166,0.25)] dark:shadow-[0_0_12px_rgba(45,212,191,0.2)] ring-1 ring-accent/50'
          : 'border-line/60 bg-surface-1/40 hover:border-line-strong hover:bg-surface-2/40',
        classNames.root ?? '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="flex items-center gap-2">
        <span className={['w-4 shrink-0 font-mono text-[10px] text-ink-faint', classNames.rank ?? ''].join(' ')}>
          {rank}
        </span>
        <span
          title={habitation.name}
          className={['flex-1 truncate text-[13px] font-semibold text-ink', classNames.name ?? ''].join(' ')}
        >
          {habitation.name}
        </span>
        {showRegime && habitation.hazard_regime ? (
          <RegimeChip
            regime={habitation.hazard_regime}
            showLabel={false}
            title={
              habitation.relocation_pathway
                ? `${habitation.hazard_regime.replace('_', ' ')} · ${PATHWAY_LABELS[habitation.relocation_pathway]}`
                : undefined
            }
          />
        ) : null}
        <div data-tier-breathing={isImmediate ? '' : undefined}>
          <TierBadge tier={habitation.tier} />
        </div>
      </div>

      <div className={['flex items-center gap-2 pl-6 text-[10px] text-ink-faint', classNames.meta ?? ''].join(' ')}>
        <span className="truncate">{habitation.admin_name ?? 'Unknown district'}</span>
        <span aria-hidden>·</span>
        <span className="font-mono tabular-nums">{formatCount(habitation.households)} HH</span>
        <span aria-hidden>·</span>
        <span className="font-mono tabular-nums" title="Share of the habitation inside a potential red zone">
          {formatPercent(habitation.prz_overlap_pct / 100)} PRZ
        </span>
        <span
          className={['ml-auto font-mono tabular-nums text-ink font-medium', classNames.score ?? ''].join(' ')}
          title="Priority score"
        >
          {formatScore(habitation.priority_score)}
        </span>
      </div>
    </button>
  );
};
