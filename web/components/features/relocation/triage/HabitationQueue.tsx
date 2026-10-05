'use client';

import { useMemo, useRef, useState } from 'react';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';

import { EmptyState, ErrorState, SectionHeader } from '@/components/common';
import { Button } from '@/components/ui';
import { M3_DURATION, M3_EASE } from '@/lib/motion/m3';
import { usePrefersReducedMotion } from '@/lib/hooks/usePrefersReducedMotion';
import type { ApiError } from '@/lib/api/client';
import type { HabitationListItem, HazardRegime } from '@/lib/api/types';
import type { RegimeFilter } from '@/lib/hooks/useRankedCells';
import { RegimeFilterBar } from '@/components/features/triage/RegimeFilterBar';

import { HabitationQueueRow } from './HabitationQueueRow';
import { HabitationQueueSkeleton } from './HabitationQueueSkeleton';

export interface HabitationQueueProps {
  habitations: HabitationListItem[];
  total?: number;
  isLoading?: boolean;
  error?: ApiError | null;
  selectedId?: number | null;
  onSelect?: (habitation: HabitationListItem) => void;
  onRetry?: () => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** Controls rendered to the right of the title, such as a district filter. */
  actionSlot?: React.ReactNode;
  /** Regime filter applied by the parent (server-side). Omit `onRegimeChange` to hide the chips. */
  regime?: RegimeFilter;
  onRegimeChange?: (regime: HazardRegime | undefined) => void;
  /** Callback to collapse the left panel. */
  onToggleCollapse?: () => void;
  className?: string;
  classNames?: {
    root?: string;
    header?: string;
    list?: string;
    search?: string;
  };
  animation?: {
    disabled?: boolean;
    stagger?: number;
    duration?: number;
  };
}

/** The demand side of the plan: habitations ranked by triage priority. */
export const HabitationQueue = ({
  habitations,
  total,
  isLoading = false,
  error = null,
  selectedId = null,
  onSelect,
  onRetry,
  title = 'Triage queue',
  description,
  actionSlot,
  regime = 'all',
  onRegimeChange,
  onToggleCollapse,
  className = '',
  classNames = {},
  animation = {},
}: HabitationQueueProps) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [searchQuery, setSearchQuery] = useState('');

  const {
    disabled: animationDisabled = false,
    stagger = 0.035,
    duration = M3_DURATION.medium2,
  } = animation;
  const animate = !animationDisabled && !prefersReducedMotion;

  const filteredHabitations = useMemo(() => {
    if (!searchQuery.trim()) return habitations;
    const q = searchQuery.toLowerCase().trim();
    return habitations.filter((h) => h.name.toLowerCase().includes(q));
  }, [habitations, searchQuery]);

  useGSAP(
    () => {
      if (!animate || filteredHabitations.length === 0) return;
      gsap.fromTo(
        '[data-habitation-row]',
        { y: 10, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration,
          stagger,
          ease: M3_EASE.decelerate,
          clearProps: 'transform,opacity',
        }
      );
    },
    { scope: rootRef, dependencies: [filteredHabitations, animate, duration, stagger] },
  );

  return (
    <div
      ref={rootRef}
      className={['flex h-full min-h-0 flex-col gap-3', classNames.root ?? '', className].filter(Boolean).join(' ')}
    >
      <div className="flex items-start justify-between gap-2">
        <SectionHeader
          title={title}
          description={
            description ??
            (total !== undefined
              ? `${habitations.length} of ${total.toLocaleString()} habitations`
              : undefined)
          }
          className={classNames.header}
        />
        {onToggleCollapse && (
          <button
            type="button"
            onClick={onToggleCollapse}
            title="Collapse triage queue"
            aria-label="Collapse triage queue"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-line/60 bg-surface-1/60 text-ink-muted hover:border-line-strong hover:bg-surface-2 hover:text-ink transition-all active:scale-95 cursor-pointer"
          >
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth="2.5"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}
      </div>

      {actionSlot ? <div>{actionSlot}</div> : null}

      {/* Search filter input */}
      <div className="relative">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Filter habitations..."
          className="w-full rounded-xl border border-line/60 bg-surface-1/40 px-3 py-1.5 pl-8 text-[12px] text-ink placeholder:text-ink-faint focus:border-accent focus:bg-surface-0 focus:outline-hidden transition-colors"
        />
        <svg
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          strokeWidth="2"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
        {searchQuery ? (
          <button
            type="button"
            onClick={() => setSearchQuery('')}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink cursor-pointer"
          >
            ✕
          </button>
        ) : null}
      </div>

      {onRegimeChange ? (
        <RegimeFilterBar
          selected={regime}
          onChange={(next) => onRegimeChange(next === 'all' ? undefined : next)}
        />
      ) : null}

      {error ? (
        <ErrorState
          message={error.message}
          code={error.code}
          requestId={error.requestId}
          actionSlot={
            onRetry ? (
              <Button size="sm" variant="secondary" onClick={onRetry}>
                Retry
              </Button>
            ) : null
          }
        />
      ) : isLoading ? (
        <HabitationQueueSkeleton />
      ) : filteredHabitations.length === 0 ? (
        <EmptyState
          title="No habitations match"
          description={
            searchQuery
              ? `No habitations matching "${searchQuery}".`
              : 'No triaged habitations match the current district and tier filter.'
          }
        />
      ) : (
        <div
          className={['flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-0.5', classNames.list ?? ''].join(' ')}
        >
          {filteredHabitations.map((habitation, index) => (
            <HabitationQueueRow
              key={habitation.id}
              habitation={habitation}
              rank={index + 1}
              isSelected={habitation.id === selectedId}
              onSelect={onSelect}
              animation={{ disabled: !animate }}
            />
          ))}
        </div>
      )}
    </div>
  );
};
