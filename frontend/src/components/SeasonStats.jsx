function fmt(v) { return v == null ? '—' : `${(v * 100).toFixed(1)}%` }
function roi(v) {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

function RecordRow({ label, record, accentColor }) {
  const isPositive = record.roi_at_110 != null && record.roi_at_110 > 0
  return (
    <div className="flex items-center justify-between gap-4 py-1.5 border-b border-violet-50 dark:border-violet-500/[0.06] last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${accentColor}`} />
        <span className="text-xs font-medium text-slate-400 truncate">{label}</span>
      </div>
      {record.total === 0 ? (
        <span className="text-xs text-slate-600 font-mono">No picks</span>
      ) : (
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs font-mono font-bold text-slate-200">
            {record.wins}–{record.losses}
          </span>
          <span className="text-xs font-mono text-slate-500">{fmt(record.win_pct)}</span>
          <span className={`text-xs font-mono font-semibold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {roi(record.roi_at_110)}
          </span>
          <span className="text-[10px] font-mono text-slate-600">({record.total})</span>
        </div>
      )}
    </div>
  )
}

function YearBlock({ data, isCurrent }) {
  return (
    <div className="rounded-xl bg-white dark:bg-[#100e22] border border-violet-200 dark:border-violet-500/[0.12] p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-bold text-gray-900 dark:text-slate-200 font-mono">{data.year}</span>
        {isCurrent && (
          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-500/[0.12] text-violet-400 ring-1 ring-violet-500/25 uppercase tracking-wide">
            Live
          </span>
        )}
        <span className="ml-auto text-[10px] font-mono text-slate-600">{data.total_games}g</span>
      </div>
      <RecordRow label="Model picks" record={data.model_picks} accentColor="bg-emerald-500" />
      <RecordRow label="YRFI signal" record={data.yrfi_signal} accentColor="bg-sky-500" />
    </div>
  )
}

export default function SeasonStats({ stats, loading }) {
  if (loading || !stats) return null

  return (
    <div className="mb-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[10px] uppercase tracking-widest font-semibold text-violet-500/60 dark:text-violet-400/40">Season Performance</span>
        <div className="flex-1 h-px bg-violet-200 dark:bg-violet-500/[0.10]" />
        <span className="text-[10px] font-mono text-violet-400/40 dark:text-violet-400/30">ROI at −110</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <YearBlock data={stats.current_year} isCurrent={true} />
        <YearBlock data={stats.prior_year}   isCurrent={false} />
      </div>
    </div>
  )
}
