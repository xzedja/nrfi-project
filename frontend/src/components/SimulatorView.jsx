import { useState } from 'react'
import { useSimulator } from '../hooks/useSimulator'
import BankrollChart from './BankrollChart'

const CURRENT_YEAR = new Date().getFullYear()

const YEAR_OPTIONS = [
  { label: 'This Year',             value: CURRENT_YEAR },
  { label: String(CURRENT_YEAR - 1), value: CURRENT_YEAR - 1 },
  { label: String(CURRENT_YEAR - 2), value: CURRENT_YEAR - 2 },
  { label: String(CURRENT_YEAR - 3), value: CURRENT_YEAR - 3 },
  { label: 'All Time',              value: 2015 },
]

function computeRecord(entries, filterFn, winFn) {
  let wins = 0, losses = 0
  for (const e of entries) {
    if (!filterFn(e)) continue
    if (winFn(e)) wins++; else losses++
  }
  const total = wins + losses
  const roi = total > 0 ? (wins * 1.0 - losses * 1.1) / (total * 1.1) : null
  return { wins, losses, total, roi }
}

function StatCard({ title, record, color, note }) {
  const dotColor = color === 'emerald' ? 'bg-emerald-500' : 'bg-sky-500'
  const roi = record.roi

  return (
    <div className="rounded-xl bg-white dark:bg-[#100e22] border border-violet-200 dark:border-violet-500/[0.12] p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className={`w-2 h-2 rounded-full ${dotColor}`} />
        <span className="text-sm font-bold text-slate-700 dark:text-slate-300">{title}</span>
      </div>
      {record.total === 0 ? (
        <p className="text-slate-600 text-sm font-mono">No picks</p>
      ) : (
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <p className="text-2xl font-black font-mono text-gray-900 dark:text-slate-200 tabular-nums">
              {record.wins}–{record.losses}
            </p>
            <p className="text-[11px] font-mono text-slate-500 mt-0.5">
              {record.total} bets · {((record.wins / record.total) * 100).toFixed(1)}% win rate
            </p>
          </div>
          <div className="ml-auto text-right">
            <p className={`text-2xl font-black font-mono tabular-nums ${roi != null && roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {roi != null ? `${roi >= 0 ? '+' : ''}${(roi * 100).toFixed(1)}%` : '—'}
            </p>
            <p className="text-[11px] font-mono text-slate-500 mt-0.5">ROI at −110</p>
          </div>
        </div>
      )}
      <p className="text-[10px] text-violet-400/30 dark:text-violet-400/25 mt-2.5 font-mono">{note}</p>
    </div>
  )
}

export default function SimulatorView() {
  const [startYear, setStartYear] = useState(CURRENT_YEAR)
  const { entries, loading, error } = useSimulator(startYear)

  const modelRecord = computeRecord(
    entries,
    e => (e.signal === 'nrfi_strong' || e.signal === 'nrfi_lean') && e.edge != null,
    e => e.nrfi_result === true,
  )
  const yrfiRecord = computeRecord(
    entries,
    e => e.signal === 'yrfi_signal',
    e => e.nrfi_result === false,
  )

  return (
    <div>
      {/* Year selector */}
      <div className="flex items-center gap-2 mb-6 flex-wrap">
        {YEAR_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => setStartYear(opt.value)}
            className={`h-8 px-3.5 rounded-lg text-xs font-semibold transition-all ${
              startYear === opt.value
                ? 'bg-violet-500/[0.15] text-violet-300 ring-1 ring-violet-500/30'
                : 'bg-violet-500/[0.05] text-violet-400/40 hover:text-violet-400/70 ring-1 ring-violet-500/[0.10]'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex justify-center py-20 gap-3">
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.3s]" />
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.15s]" />
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce" />
        </div>
      )}

      {error && (
        <div className="rounded-xl bg-red-950/40 border border-red-800/40 p-5 text-red-400 text-sm">{error}</div>
      )}

      {!loading && !error && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <StatCard
              title="Model Picks"
              record={modelRecord}
              color="emerald"
              note="Bet NRFI when model edge > 0 · flat -110"
            />
            <StatCard
              title="YRFI Signal"
              record={yrfiRecord}
              color="sky"
              note="Bet YRFI when market implies ≥60% NRFI · flat -110"
            />
          </div>

          {/* Chart */}
          <div className="rounded-xl bg-white dark:bg-[#100e22] border border-violet-200 dark:border-violet-500/[0.12] p-5">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-[10px] uppercase tracking-widest font-semibold text-violet-400/40">
                Running P&amp;L
              </span>
              <div className="flex-1 h-px bg-violet-200 dark:bg-violet-500/[0.10]" />
              <span className="text-[10px] font-mono text-violet-400/30">1 unit = 1 bet at −110</span>
            </div>
            <BankrollChart entries={entries} />
          </div>
        </>
      )}
    </div>
  )
}
