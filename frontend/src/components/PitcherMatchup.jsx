import { pct, fmtEra, fmtVelo, fmtRest } from '../utils/signal'

function Chip({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1 border-b border-gray-100 dark:border-white/[0.03] last:border-0">
      <span className="text-[11px] text-gray-500 dark:text-slate-500 shrink-0">{label}</span>
      <span className="text-[11px] font-mono font-medium text-gray-700 dark:text-slate-300 tabular-nums">{value}</span>
    </div>
  )
}

function NrfiChip({ record }) {
  if (!record) return null
  const rate = record.nrfi_rate != null ? pct(record.nrfi_rate) : '—'
  const frac = `${record.nrfi_wins}/${record.total}`
  return (
    <div className="flex items-center justify-between gap-2 py-1 border-b border-gray-100 dark:border-white/[0.03]">
      <span className="text-[11px] text-gray-500 dark:text-slate-500 shrink-0">{record.year} NRFI</span>
      <span className="text-[11px] font-mono font-semibold text-gray-700 dark:text-slate-300 tabular-nums">
        {rate} <span className="text-gray-400 dark:text-slate-600 font-normal">({frac})</span>
      </span>
    </div>
  )
}

function PitcherPanel({ pitcher, role }) {
  const hand = pitcher?.throws ? ` ${pitcher.throws}HP` : ''
  const name = pitcher?.name ?? 'TBD'

  return (
    <div className="flex-1 min-w-0">
      <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-1.5">{role}</p>
      <p className="text-sm font-bold text-gray-900 dark:text-white leading-tight truncate mb-2">
        {name}
        {hand && <span className="text-gray-400 dark:text-slate-500 font-normal text-[11px] ml-1.5">{hand}</span>}
      </p>
      <div>
        <NrfiChip record={pitcher?.nrfi_current} />
        <NrfiChip record={pitcher?.nrfi_prior} />
        <Chip label="L5 ERA"    value={fmtEra(pitcher?.last5_era)} />
        <Chip label="1st ERA"   value={fmtEra(pitcher?.first_inn_era)} />
        <Chip label="Hold %"    value={pct(pitcher?.hold_rate)} />
        <Chip label="Fastball"  value={fmtVelo(pitcher?.avg_velo, pitcher?.velo_trend)} />
        <Chip label="Rest"      value={fmtRest(pitcher?.days_rest)} />
        <Chip label="1st K%"    value={pct(pitcher?.first_inn_k_pct)} />
        <Chip label="1st BB%"   value={pct(pitcher?.first_inn_bb_pct)} />
      </div>
    </div>
  )
}

export default function PitcherMatchup({ awaySp, homeSp }) {
  return (
    <div className="px-4 py-3 flex gap-4">
      <PitcherPanel pitcher={awaySp} role="Away SP" />
      <div className="w-px bg-gray-200 dark:bg-white/[0.06] shrink-0" />
      <PitcherPanel pitcher={homeSp} role="Home SP" />
    </div>
  )
}
