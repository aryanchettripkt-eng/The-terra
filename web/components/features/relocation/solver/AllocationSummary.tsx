import { MetricCard } from '@/components/common';
import type { AllocationPlanResponse } from '@/lib/api/types';

import { AllocationRegimeBreakdown } from './AllocationRegimeBreakdown';
import { UnmetDemandMeter } from './UnmetDemandMeter';

export interface AllocationSummaryProps {
  plan: AllocationPlanResponse;
  className?: string;
  classNames?: {
    root?: string;
    metrics?: string;
    meter?: string;
    regimes?: string;
    provenance?: string;
  };
}

/** Headline outcome of one allocation run. */
export const AllocationSummary = ({
  plan,
  className = '',
  classNames = {},
}: AllocationSummaryProps) => (
  <div
    data-allocation-summary
    className={['flex flex-col gap-3', classNames.root ?? '', className].filter(Boolean).join(' ')}
  >
    <div className={['grid grid-cols-2 gap-2', classNames.metrics ?? ''].join(' ')}>
      <MetricCard
        label="Placed"
        value={plan.total_relocated_households.toLocaleString()}
        numericValue={plan.total_relocated_households}
        formatNumeric={(value) => Math.round(value).toLocaleString()}
        description="households"
        variant={plan.total_relocated_households > 0 ? 'safe' : 'critical'}
      />
      <MetricCard
        label="Unmet"
        value={plan.unmet_demand_households.toLocaleString()}
        numericValue={plan.unmet_demand_households}
        formatNumeric={(value) => Math.round(value).toLocaleString()}
        description="households"
        variant={plan.unmet_demand_households > 0 ? 'critical' : 'safe'}
      />
    </div>

    <UnmetDemandMeter
      placedHouseholds={plan.total_relocated_households}
      unmetHouseholds={plan.unmet_demand_households}
      totalHouseholds={plan.total_demand_households}
      className={classNames.meter}
    />

    <AllocationRegimeBreakdown breakdown={plan.regime_breakdown ?? []} className={classNames.regimes} />

    <p className={['text-[10px] text-ink-faint', classNames.provenance ?? ''].join(' ')}>
      Run {plan.allocation_run_id.slice(0, 8)} · {plan.status.toLowerCase()} ·{' '}
      solved in {plan.solver_latency_ms.toFixed(1)} ms
    </p>
  </div>
);
