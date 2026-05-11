import { getSignal, pct, fmtEdge } from '../utils/signal'

function edgeColorClass(edge) {
  if (edge == null)   return 'text-violet-400/50'
  if (edge >= 0.05)   return 'text-emerald-400'
  if (edge >= 0.02)   return 'text-amber-400'
  if (edge > 0)       return 'text-amber-500/70'
  if (edge <= -0.05)  return 'text-red-400'
  if (edge <= -0.02)  return 'text-orange-400'
  return 'text-orange-500/70'
}

const labelCls = 'text-[10px] uppercase tracking-widest text-violet-400/60 dark:text-violet-400/40 mb-1'
const subCls   = 'text-[10px] text-violet-400/40 dark:text-violet-400/30 mt-0.5'

function VariantPill({ label, p, pMarket, color }) {
  if (p == null) return null
  const varEdge = pMarket != null ? p - pMarket : null
  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded ${color}`}>
        {label}
      </span>
      <span className="text-[11px] font-mono font-semibold text-slate-400 tabular-nums">
        {pct(p)}
      </span>
      {varEdge != null && (
        <span className={`text-[10px] font-mono tabular-nums ${edgeColorClass(varEdge)}`}>
          {fmtEdge(varEdge)}
        </span>
      )}
    </div>
  )
}

export default function ProbabilityBoxes({ pModel, pMarket, edge, signal, isHighDisagreement, varA, varB }) {
  const sig = getSignal(signal)
  const hasVariants = varA != null || varB != null

  return (
    <div className="px-4 py-4">
      {/* Three stat columns */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        <div>
          <p className={labelCls}>Model</p>
          <p className={`text-2xl font-black font-mono tabular-nums ${sig.edgeColor}`}>
            {pct(pModel)}
          </p>
          <p className={subCls}>P(NRFI)</p>
        </div>

        <div>
          <p className={labelCls}>Market</p>
          <p className="text-2xl font-black font-mono tabular-nums text-gray-600 dark:text-slate-300">
            {pct(pMarket)}
          </p>
          <p className={subCls}>Implied</p>
        </div>

        <div className="text-right">
          <p className={labelCls}>Edge</p>
          <p className={`text-2xl font-black font-mono tabular-nums ${edgeColorClass(edge)}`}>
            {fmtEdge(edge)}
          </p>
          <p className={subCls}>vs Market</p>
        </div>
      </div>

      {/* Gauge bar */}
      <div className="relative h-1.5 bg-violet-100 dark:bg-violet-950/60 rounded-full overflow-hidden">
        {pMarket != null && (
          <div
            className="absolute left-0 top-0 h-full bg-violet-300/50 dark:bg-violet-700/40 rounded-full transition-all"
            style={{ width: `${Math.min(pMarket * 100, 100)}%` }}
          />
        )}
        {pModel != null && (
          <div
            className={`absolute top-0 h-full w-0.5 ${sig.gaugeColor} transition-all`}
            style={{ left: `calc(${Math.min(pModel * 100, 100)}% - 1px)` }}
          />
        )}
      </div>
      <div className="flex justify-between text-[9px] font-mono text-violet-400/40 dark:text-violet-400/25 mt-0.5">
        <span>0%</span>
        <span>↑ mkt &nbsp;|&nbsp; ▏model</span>
        <span>100%</span>
      </div>

      {/* Variant comparison row */}
      {hasVariants && (
        <div className="mt-2.5 pt-2 border-t border-violet-100/60 dark:border-violet-500/[0.08]">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-[9px] uppercase tracking-widest text-violet-400/40 shrink-0">Variants</span>
            <VariantPill
              label="A"
              p={varA}
              pMarket={pMarket}
              color="text-emerald-400/70 bg-emerald-500/[0.08] ring-1 ring-emerald-500/15"
            />
            <VariantPill
              label="B"
              p={varB}
              pMarket={pMarket}
              color="text-amber-400/70 bg-amber-500/[0.08] ring-1 ring-amber-500/15"
            />
          </div>
        </div>
      )}

      {isHighDisagreement && (
        <p className="mt-2 text-[11px] text-amber-500/80 flex items-center gap-1.5">
          <span>⚠</span>
          <span>Edge ≥7% — likely model data issue, not a bet</span>
        </p>
      )}
    </div>
  )
}
