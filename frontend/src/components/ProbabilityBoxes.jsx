import { pct, fmtEdge } from '../utils/signal'

function Box({ label, value, valueClass, sub }) {
  return (
    <div className="bg-gray-100 dark:bg-slate-800 rounded-xl p-3 text-center">
      <p className="text-xs text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-black tabular-nums ${valueClass}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 dark:text-slate-600 mt-0.5">{sub}</p>}
    </div>
  )
}

function edgeClass(edge) {
  if (edge == null)    return 'text-gray-400 dark:text-slate-400'
  if (edge >= 0.05)    return 'text-green-600 dark:text-green-400'
  if (edge >= 0.02)    return 'text-green-500'
  if (edge > 0)        return 'text-yellow-600 dark:text-yellow-400'
  if (edge <= -0.05)   return 'text-red-600 dark:text-red-400'
  if (edge <= -0.02)   return 'text-red-500'
  return 'text-orange-600 dark:text-orange-400'
}

export default function ProbabilityBoxes({ pModel, pMarket, edge, isHighDisagreement }) {
  return (
    <div className="mx-5 mb-4">
      <div className="grid grid-cols-3 gap-2">
        <Box label="Model"  value={pct(pModel)}   valueClass="text-gray-900 dark:text-white"       sub="P(NRFI)" />
        <Box label="Market" value={pct(pMarket)}  valueClass="text-gray-600 dark:text-slate-300"   sub="Implied" />
        <Box label="Edge"   value={fmtEdge(edge)} valueClass={edgeClass(edge)}                     sub="vs Market" />
      </div>
      {isHighDisagreement && (
        <p className="mt-2 text-xs text-amber-600 dark:text-amber-500/80 text-center">
          ⚠ Edge ≥7% — likely model data issue, not a bet
        </p>
      )}
    </div>
  )
}
