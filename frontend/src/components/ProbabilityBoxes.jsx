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

function VariantRow({ label, p, pMarket }) {
  if (p == null) return null
  const varEdge = pMarket != null ? p - pMarket : null
  const isLean  = varEdge != null && varEdge > 0
  const isFade  = varEdge != null && varEdge < 0

  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] font-bold uppercase tracking-widest w-3 text-violet-400/50">
        {label}
      </span>
      <span className="text-[11px] font-mono font-semibold text-slate-300 tabular-nums w-8">
        {pct(p)}
      </span>
      {varEdge != null ? (
        <>
          <span className={`text-[10px] font-mono tabular-nums w-9 ${edgeColorClass(varEdge)}`}>
            {fmtEdge(varEdge)}
          </span>
          <span className={`text-[9px] font-bold uppercase tracking-wider ${
            isLean ? 'text-emerald-400/80' : isFade ? 'text-red-400/80' : 'text-slate-600'
          }`}>
            {isLean ? 'LEAN' : isFade ? 'FADE' : '—'}
          </span>
        </>
      ) : (
        <span className="text-[10px] text-slate-600">—</span>
      )}
    </div>
  )
}

export default function ProbabilityBoxes({ pModel, pMarket, edge, signal, isHighDisagreement, varA, varB }) {
  const sig = getSignal(signal)
  const hasVariants = varA != null || varB != null

  const varAEdge = varA != null && pMarket != null ? varA - pMarket : null
  const varBEdge = varB != null && pMarket != null ? varB - pMarket : null

  // Consensus: count models that have positive edge (lean NRFI)
  let consensusCount = null
  if (hasVariants && pMarket != null) {
    const baseLean = edge != null && edge > 0
    const aLean    = varAEdge != null && varAEdge > 0
    const bLean    = varBEdge != null && varBEdge > 0
    const total    = 1 + (varA != null ? 1 : 0) + (varB != null ? 1 : 0)
    const leanCount = [baseLean, varA != null && aLean, varB != null && bLean].filter(Boolean).length
    consensusCount = { lean: leanCount, total }
  }

  const allAgree    = consensusCount && consensusCount.lean === consensusCount.total
  const noneAgree   = consensusCount && consensusCount.lean === 0
  const isSplit     = consensusCount && !allAgree && !noneAgree

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
            className="animate-gauge absolute left-0 top-0 h-full bg-violet-300/50 dark:bg-violet-700/40 rounded-full"
            style={{ width: `${Math.min(pMarket * 100, 100)}%` }}
          />
        )}
        {pModel != null && (
          <div
            className={`animate-gauge absolute top-0 h-full w-0.5 ${sig.gaugeColor}`}
            style={{ left: `calc(${Math.min(pModel * 100, 100)}% - 1px)` }}
          />
        )}
      </div>
      <div className="flex justify-between text-[9px] font-mono text-violet-400/40 dark:text-violet-400/25 mt-0.5">
        <span>0%</span>
        <span>↑ mkt &nbsp;|&nbsp; ▏model</span>
        <span>100%</span>
      </div>

      {/* Variant rows */}
      {hasVariants && (
        <div className="mt-2.5 pt-2 border-t border-violet-100/60 dark:border-violet-500/[0.08]">
          <p className="text-[9px] uppercase tracking-widest text-violet-400/40 mb-1.5">Variants</p>
          <div className="space-y-1">
            <VariantRow label="A" p={varA} pMarket={pMarket} />
            <VariantRow label="B" p={varB} pMarket={pMarket} />
          </div>

          {consensusCount && (
            <div className={`mt-1.5 text-[10px] font-semibold flex items-center gap-1 ${
              allAgree  ? 'text-emerald-400/70' :
              noneAgree ? 'text-orange-400/70' :
              'text-amber-400/60'
            }`}>
              <span>{allAgree ? '✓' : '⚠'}</span>
              <span>
                {allAgree
                  ? `All ${consensusCount.total} lean NRFI`
                  : noneAgree
                  ? 'All models lean YRFI'
                  : `${consensusCount.lean}/${consensusCount.total} lean NRFI`}
              </span>
            </div>
          )}
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
