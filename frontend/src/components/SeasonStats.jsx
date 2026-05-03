function pct(v) {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}
function roi(v) {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}
function roiColor(v) {
  if (v == null) return 'text-gray-400 dark:text-slate-400'
  return v > 0
    ? 'text-emerald-600 dark:text-emerald-400'
    : 'text-red-600 dark:text-red-400'
}

function RecordBlock({ label, record, accent }) {
  const dotColor = accent === 'blue'
    ? 'bg-blue-500'
    : record.roi_at_110 != null && record.roi_at_110 > 0
      ? 'bg-emerald-500'
      : 'bg-gray-400 dark:bg-slate-500'

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`w-2 h-2 rounded-full ${dotColor} shrink-0`} />
        <span className="text-xs font-semibold text-gray-600 dark:text-slate-300 uppercase tracking-wide">{label}</span>
      </div>
      {record.total === 0 ? (
        <span className="text-xs text-gray-400 dark:text-slate-500">No picks yet</span>
      ) : (
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="text-sm font-bold text-gray-900 dark:text-slate-100">
            {record.wins}–{record.losses}
          </span>
          <span className="text-xs text-gray-500 dark:text-slate-400">{pct(record.win_pct)} win</span>
          <span className={`text-xs font-semibold ${roiColor(record.roi_at_110)}`}>
            {roi(record.roi_at_110)} ROI
          </span>
          <span className="text-xs text-gray-300 dark:text-slate-600">({record.total} picks)</span>
        </div>
      )}
    </div>
  )
}

function YearCard({ data, isCurrent }) {
  return (
    <div className="rounded-xl bg-white dark:bg-slate-900/60 border border-gray-200 dark:border-slate-800/60 p-4 flex flex-col gap-3 shadow-sm">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-sm font-bold text-gray-900 dark:text-slate-200">{data.year}</span>
        {isCurrent && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/40 uppercase tracking-wide">
            In Progress
          </span>
        )}
        <span className="text-xs text-gray-400 dark:text-slate-500 ml-auto">{data.total_games} games</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <RecordBlock label="Model Picks" record={data.model_picks} accent="green" />
        <RecordBlock label="YRFI Signal" record={data.yrfi_signal} accent="blue" />
      </div>
    </div>
  )
}

export default function SeasonStats({ stats, loading }) {
  if (loading || !stats) return null

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-xs font-semibold text-gray-400 dark:text-slate-400 uppercase tracking-widest whitespace-nowrap">
          Season Performance
        </h2>
        <div className="flex-1 h-px bg-gray-200 dark:bg-slate-800" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <YearCard data={stats.current_year} isCurrent={true} />
        <YearCard data={stats.prior_year} isCurrent={false} />
      </div>
      <p className="mt-2 text-[11px] text-gray-300 dark:text-slate-600 text-right">
        ROI at –110 · Model picks = edge &gt; 0 · YRFI signal = market ≥60% NRFI
      </p>
    </div>
  )
}
