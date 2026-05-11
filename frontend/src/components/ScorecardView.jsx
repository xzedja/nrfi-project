import { useScorecard } from '../hooks/useScorecard'

function fmt(v)  { return v == null ? '—' : `${(v * 100).toFixed(1)}%` }
function roi(v)  { return v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%` }

const VARIANT_STYLE = {
  baseline: {
    bar:   'bg-violet-500',
    badge: 'text-violet-400 bg-violet-500/[0.10] ring-1 ring-violet-500/20',
  },
  var_a: {
    bar:   'bg-emerald-500',
    badge: 'text-emerald-400 bg-emerald-500/[0.10] ring-1 ring-emerald-500/20',
  },
  var_b: {
    bar:   'bg-amber-500',
    badge: 'text-amber-400 bg-amber-500/[0.10] ring-1 ring-amber-500/20',
  },
}

function RecordBlock({ year, record, isCurrent }) {
  const pos = record.roi_at_110 != null && record.roi_at_110 > 0
  return (
    <div className={`rounded-lg px-3 py-2.5 ${
      isCurrent
        ? 'bg-violet-50/60 dark:bg-violet-950/30 ring-1 ring-violet-200 dark:ring-violet-500/20'
        : 'bg-gray-50 dark:bg-white/[0.03] ring-1 ring-gray-100 dark:ring-white/[0.04]'
    }`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-mono font-semibold text-slate-500">{year}</span>
        {isCurrent && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/[0.12] text-violet-400 font-bold uppercase tracking-wide ring-1 ring-violet-500/20">
            Live
          </span>
        )}
      </div>
      {record.total === 0 ? (
        <p className="text-xs text-slate-600 font-mono">No picks yet</p>
      ) : (
        <>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-xl font-black font-mono tabular-nums text-slate-200">
              {record.wins}–{record.losses}
            </span>
            <span className={`text-sm font-bold font-mono tabular-nums ${pos ? 'text-emerald-400' : 'text-red-400'}`}>
              {roi(record.roi_at_110)}
            </span>
          </div>
          <div className="flex justify-between mt-0.5">
            <span className="text-[10px] font-mono text-slate-500">{fmt(record.win_pct)} hit</span>
            <span className="text-[10px] font-mono text-slate-600">{record.total} picks</span>
          </div>
        </>
      )}
    </div>
  )
}

function VariantCard({ v }) {
  const style = VARIANT_STYLE[v.variant] || VARIANT_STYLE.baseline

  return (
    <div className="rounded-xl border border-violet-200 dark:border-violet-500/[0.12] bg-white dark:bg-[#100e22] overflow-hidden flex flex-col">
      <div className={`h-0.5 ${style.bar}`} />
      <div className="px-4 pt-4 pb-3">
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-slate-200">{v.display_name}</h3>
          <span className={`text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded shrink-0 ${style.badge}`}>
            {v.variant}
          </span>
        </div>
        <p className="text-[11px] text-slate-500 dark:text-slate-600 leading-relaxed">{v.description}</p>
      </div>
      <div className="px-4 pb-4 space-y-2 flex-1">
        <RecordBlock year={v.current_year} record={v.current_record} isCurrent={true} />
        <RecordBlock year={v.prior_year}   record={v.prior_record}   isCurrent={false} />
      </div>
    </div>
  )
}

export default function ScorecardView() {
  const { scorecard, loading, error } = useScorecard()

  return (
    <div>
      {/* Header */}
      <div className="mb-5">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] uppercase tracking-widest font-semibold text-violet-500/60 dark:text-violet-400/40">
            Model Scorecard
          </span>
          <div className="flex-1 h-px bg-violet-200 dark:bg-violet-500/[0.10]" />
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-600 leading-relaxed max-w-2xl">
          Three variants trained on the same data with different feature emphasis. Edge picks = model probability above market (NRFI lean). ROI assumes −110 juice.
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-24 gap-3">
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.3s]" />
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.15s]" />
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce" />
        </div>
      )}

      {error && (
        <div className="rounded-xl bg-red-950/40 border border-red-800/40 p-5 text-red-400 text-sm">
          <p className="font-semibold mb-1">Failed to load scorecard</p>
          <p className="text-red-500/70">{error}</p>
        </div>
      )}

      {!loading && !error && scorecard && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {scorecard.variants.map(v => (
              <VariantCard key={v.variant} v={v} />
            ))}
          </div>

          <div className="mt-4 rounded-lg bg-violet-50/50 dark:bg-violet-950/20 border border-violet-200 dark:border-violet-500/[0.10] px-4 py-3">
            <p className="text-[11px] text-violet-400/60 leading-relaxed">
              Var A and Var B models are active starting {new Date().getFullYear()} — prior-year records will populate as historical variant predictions are backfilled.
              Live records accumulate daily from the morning pipeline.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
