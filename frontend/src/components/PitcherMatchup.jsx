import { pct, fmtEra, fmtVelo, fmtRest } from '../utils/signal'

function StatRow({ label, value }) {
  return (
    <div className="flex justify-between items-baseline gap-2">
      <span className="text-xs text-gray-500 dark:text-slate-500 shrink-0">{label}</span>
      <span className="text-xs font-medium tabular-nums text-gray-700 dark:text-slate-300">
        {value}
      </span>
    </div>
  )
}

function NrfiStatRow({ record }) {
  if (!record) return null
  const rate = record.nrfi_rate != null ? pct(record.nrfi_rate) : '—'
  return (
    <div className="flex justify-between items-baseline gap-2">
      <span className="text-xs text-gray-500 dark:text-slate-500 shrink-0">{record.year} NRFI</span>
      <span className="text-xs font-semibold tabular-nums text-gray-700 dark:text-slate-300">
        {rate}
        <span className="font-normal text-gray-400 dark:text-slate-500 ml-1">
          ({record.nrfi_wins}/{record.total})
        </span>
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
        <p className="text-xs text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-1">{role}</p>
        <p className="text-sm font-bold text-gray-900 dark:text-white leading-tight truncate">
          {name}
          <span className="text-gray-400 dark:text-slate-500 font-normal text-xs">{hand}</span>
        </p>
      </div>
      <div className="space-y-1.5">
        {(pitcher?.nrfi_current || pitcher?.nrfi_prior) && (
          <div className="pb-1 mb-0.5 border-b border-gray-200 dark:border-slate-700/60 space-y-1.5">
            <NrfiStatRow record={pitcher?.nrfi_current} />
            <NrfiStatRow record={pitcher?.nrfi_prior} />
          </div>
        )}
        <StatRow label="L5 ERA"      value={fmtEra(pitcher?.last5_era)} />
        <StatRow label="1st Inn ERA" value={fmtEra(pitcher?.first_inn_era)} />
        <StatRow label="Hold Rate"   value={pct(pitcher?.hold_rate)} />
        <StatRow label="Fastball"    value={fmtVelo(pitcher?.avg_velo, pitcher?.velo_trend)} />
        <StatRow label="Rest"        value={fmtRest(pitcher?.days_rest)} />
        <StatRow label="1st K%"      value={pct(pitcher?.first_inn_k_pct)} />
        <StatRow label="1st BB%"     value={pct(pitcher?.first_inn_bb_pct)} />
      </div>
    </div>
  )
}

export default function PitcherMatchup({ awaySp, homeSp }) {
  return (
    <div className="mx-5 mb-4 flex bg-gray-50 dark:bg-slate-800/40 rounded-xl p-4 gap-4 border border-gray-200 dark:border-slate-800">
      <div className="flex-1 min-w-0">
        <PitcherPanel pitcher={awaySp} role="Away Starter" />
      </div>
      <div className="w-px bg-gray-200 dark:bg-slate-700/60 shrink-0" />
      <div className="flex-1 min-w-0">
        <PitcherPanel pitcher={homeSp} role="Home Starter" />
      </div>
    </div>
  )
}
