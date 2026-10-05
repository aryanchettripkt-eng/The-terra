import { SectionHeader } from '@/components/common';
import type { AllocationRegimeBreakdown as RegimeBreakdown } from '@/lib/api/types';

import { RegimeBreakdownRow } from './RegimeBreakdownRow';

export interface AllocationRegimeBreakdownProps {
  breakdown: RegimeBreakdown[];
  title?: string;
  description?: string;
  className?: string;
  classNames?: {
    root?: string;
    list?: string;
  };
}

/**
 * Outcome of an allocation run per hazard regime, char belt first.
 *
 * Char-belt households can only be resettled on the mainland, so a char-belt "unmet" figure means
 * no eligible mainland site with capacity lies within the search radius, not that the solver failed.
 */
export const AllocationRegimeBreakdown = ({
  breakdown,
  title = 'By hazard regime',
  description = 'Char-belt households are resettled on the mainland only.',
  className = '',
  classNames = {},
}: AllocationRegimeBreakdownProps) => {
  if (breakdown.length === 0) return null;

  return (
    <div className={['flex flex-col gap-2', classNames.root ?? '', className].filter(Boolean).join(' ')}>
      <SectionHeader title={title} description={description} />
      <div className={['flex flex-col gap-1.5', classNames.list ?? ''].join(' ')}>
        {breakdown.map((item) => (
          <RegimeBreakdownRow key={item.regime ?? 'none'} breakdown={item} />
        ))}
      </div>
    </div>
  );
};
