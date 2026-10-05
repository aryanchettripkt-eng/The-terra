'use client';

import { FilterChip } from '@/components/common/FilterChip';
import type { HazardRegime } from '@/lib/api/types';
import type { RegimeFilter } from '@/lib/hooks/useRankedCells';
import { REGIME_ICONS, REGIME_LABELS } from '@/lib/map/constants';

export interface RegimeFilterBarProps {
  selected: RegimeFilter;
  onChange?: (next: RegimeFilter) => void;
  /** Count per regime, shown on each chip. Omit when counts are not known (e.g. a paginated list). */
  counts?: Record<HazardRegime, number>;
  /** Regimes to offer, in display order. Defaults to the rankable ones. */
  regimes?: readonly HazardRegime[];
  allLabel?: string;
  className?: string;
}

/** Filter chips for the cell ranking: all cells, or one hazard regime. */
export const RegimeFilterBar = ({
  selected,
  onChange,
  counts,
  regimes = ['floodplain', 'char_belt'],
  allLabel = 'All',
  className = '',
}: RegimeFilterBarProps) => {
  const total = counts ? regimes.reduce((sum, regime) => sum + counts[regime], 0) : undefined;

  return (
    <div role="group" aria-label="Filter by hazard regime" className={['flex flex-wrap gap-1.5', className].filter(Boolean).join(' ')}>
      <FilterChip label={allLabel} count={total} active={selected === 'all'} onToggle={() => onChange?.('all')} />
      {regimes.map((regime) => (
        <FilterChip
          key={regime}
          label={REGIME_LABELS[regime]}
          count={counts?.[regime]}
          disabled={counts ? counts[regime] === 0 : false}
          active={selected === regime}
          leftIcon={
            <span aria-hidden className="material-symbols-outlined text-[1.2em] leading-none">
              {REGIME_ICONS[regime]}
            </span>
          }
          onToggle={() => onChange?.(selected === regime ? 'all' : regime)}
        />
      ))}
    </div>
  );
};
