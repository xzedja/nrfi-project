import { pct, fmtEra, fmtVelo, fmtRest } from '../utils/signal'

function StatRow({ label, value, highlight }) {
  return (
    <div className="flex justify-between items-baseline gap-2">
      <span className="text-xs text-slate-500 shrink-0">{label}</span>
      <span className={`text-xs font-medium tabular-nums ${highlight ? 'text-white' : 'text-slate-300'}`}>
        {value}
      </span>
    </div>
  )
}

function PitcherPanel({ pitcher, role }) {
  const hand = pitcher?.throws ? ` (${pitcher.throws})` : ''
  const name = pitcher?.name ?? 'TBD'

  return (
    <div className="space-y-2 min-w-0">
      <div>
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">{role}</p>
        <p className="text-sm font-bold text-white leading-tight truncate">
          {name}
          <span className="text-slate-500 font-normal text-xs">{hand}</span>
        </p>
      </div>
      <div className="space-y-1.5">
        <StatRow label="L5 ERA"     value={fmtEra(pitcher?.last5_era)} />
        <StatRow label="1st Inn ERA" value={fmtEra(pitcher?.first_inn_era)} />
        <StatRow label="Hold Rate"  value={pct(pitcher?.hold_rate)} />
        <StatRow label="Fastball"   value={fmtVelo(pitcher?.avg_velo, pitcher?.velo_trend)} />
        <StatRow label="Rest"       value={fmtRest(pitcher?.days_rest)} />
        <StatRow label="1st K%"     value={pct(pitcher?.first_inn_k_pct)} />
        <StatRow label="1st BB%"    value={pct(pitcher?.first_inn_bb_pct)} />
      </div>
    </div>
  )
}

export default function PitcherMatchup({ awaySp, homeSp }) {
  return (
    <div className="mx-5 mb-4 flex bg-slate-800/40 rounded-xl p-4 gap-4 border border-slate-800">
      <div className="flex-1 min-w-0">
        <PitcherPanel pitcher={awaySp} role="Away Starter" />
      </div>
      <div className="w-px bg-slate-700/60 shrink-0" />
      <div className="flex-1 min-w-0">
        <PitcherPanel pitcher={homeSp} role="Home Starter" />
      </div>
    </div>
  )
}
