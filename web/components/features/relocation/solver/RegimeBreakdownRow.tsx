import { RegimeChip } from '@/components/common/RegimeChip';
import type { AllocationRegimeBreakdown } from '@/lib/api/types';
import { PATHWAY_LABELS } from '@/lib/map/constants';

export interface RegimeBreakdownRowProps {
  breakdown: AllocationRegimeBreakdown;
  /** Label for habitations with no regime data. */
  unclassifiedLabel?: string;
  className?: string;
  classNames?: {
    root?: string;
    pathway?: string;
    counts?: string;
  };
}

/** One regime's outcome in an allocation run: how many of its households were placed. */
export const RegimeBreakdownRow = ({
  breakdown,
  unclassifiedLabel = 'No regime data',
  className = '',
  classNames = {},
}: RegimeBreakdownRowProps) => {
  const { regime, relocation_pathway, demand_households, relocated_households, unmet_households } = breakdown;

  return (
    <div
      data-regime-breakdown={regime ?? 'none'}
      className={['flex flex-col gap-1 rounded-xl border border-line/60 px-3 py-2', classNames.root ?? '', className]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="flex items-center gap-2">
        {regime ? (
          <RegimeChip regime={regime} />
        ) : (
          <span className="font-mono text-[9px] uppercase tracking-wider text-ink-faint">{unclassifiedLabel}</span>
        )}
        <span className={['text-[10px] text-ink-faint', classNames.pathway ?? ''].join(' ')}>
          {PATHWAY_LABELS[relocation_pathway]}
        </span>
      </div>
      <div className={['flex items-baseline gap-2 font-mono text-[11px] tabular-nums', classNames.counts ?? ''].join(' ')}>
        <span className="font-bold text-ink">{relocated_households.toLocaleString()}</span>
        <span className="text-ink-faint">of {demand_households.toLocaleString()} HH placed</span>
        {unmet_households > 0 ? (
          <span className="ml-auto font-bold text-critical">{unmet_households.toLocaleString()} unmet</span>
        ) : null}
      </div>
    </div>
  );
};
