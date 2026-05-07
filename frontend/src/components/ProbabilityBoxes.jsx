import { getSignal, pct, fmtEdge } from '../utils/signal'

function edgeColorClass(edge) {
  if (edge == null)   return 'text-slate-400'
  if (edge >= 0.05)   return 'text-emerald-400'
  if (edge >= 0.02)   return 'text-amber-400'
  if (edge > 0)       return 'text-amber-500/70'
  if (edge <= -0.05)  return 'text-red-400'
  if (edge <= -0.02)  return 'text-orange-400'
  return 'text-orange-500/70'
}

export default function ProbabilityBoxes({ pModel, pMarket, edge, signal, isHighDisagreement }) {
  const sig = getSignal(signal)

  return (
    <div className="px-4 py-4">
      {/* Three stat columns */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Model</p>
          <p className={`text-2xl font-black font-mono tabular-nums ${sig.edgeColor}`}>
            {pct(pModel)}
          </p>
          <p className="text-[10px] text-gray-400 dark:text-slate-600 mt-0.5">P(NRFI)</p>
        </div>

        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Market</p>
          <p className="text-2xl font-black font-mono tabular-nums text-slate-300 dark:text-slate-300">
            {pct(pMarket)}
          </p>
          <p className="text-[10px] text-gray-400 dark:text-slate-600 mt-0.5">Implied</p>
        </div>

        <div className="text-right">
          <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Edge</p>
          <p className={`text-2xl font-black font-mono tabular-nums ${edgeColorClass(edge)}`}>
            {fmtEdge(edge)}
          </p>
          <p className="text-[10px] text-gray-400 dark:text-slate-600 mt-0.5">vs Market</p>
        </div>
      </div>

      {/* Gauge bar */}
      <div className="relative h-1.5 bg-gray-200 dark:bg-slate-800 rounded-full overflow-hidden">
        {/* Market fill */}
        {pMarket != null && (
          <div
            className="absolute left-0 top-0 h-full bg-slate-500/50 rounded-full transition-all"
            style={{ width: `${Math.min(pMarket * 100, 100)}%` }}
          />
        )}
        {/* Model marker */}
        {pModel != null && (
          <div
            className={`absolute top-0 h-full w-0.5 ${sig.gaugeColor} transition-all`}
            style={{ left: `calc(${Math.min(pModel * 100, 100)}% - 1px)` }}
          />
        )}
      </div>
      <div className="flex justify-between text-[9px] font-mono text-gray-400 dark:text-slate-600 mt-0.5">
        <span>0%</span>
        <span className="text-slate-500">↑ mkt &nbsp; | &nbsp; ▏model</span>
        <span>100%</span>
      </div>

      {isHighDisagreement && (
        <p className="mt-2 text-[11px] text-amber-500/80 flex items-center gap-1.5">
          <span>⚠</span>
          <span>Edge ≥7% — likely model data issue, not a bet</span>
        </p>
      )}
    </div>
  )
}
