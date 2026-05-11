import { usePickTrend } from '../hooks/usePickTrend'

function fmt(v) { return v == null ? '—' : `${(v * 100).toFixed(1)}%` }
function roi(v) {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

// Circular arc showing win rate
function WinArc({ winPct, size = 52 }) {
  const r = size / 2 - 5
  const cx = size / 2
  const cy = size / 2
  const circumference = 2 * Math.PI * r
  const pct = Math.min(winPct ?? 0, 1)
  const dash = pct * circumference

  return (
    <svg width={size} height={size} className="-rotate-90 shrink-0">
      <circle
        cx={cx} cy={cy} r={r}
        fill="none" strokeWidth="3.5"
        className="stroke-violet-500/[0.10]"
      />
      <circle
        cx={cx} cy={cy} r={r}
        fill="none" strokeWidth="3.5"
        stroke={pct >= 0.525 ? 'rgb(52,211,153)' : pct >= 0.48 ? 'rgb(251,191,36)' : 'rgb(248,113,113)'}
        strokeDasharray={`${dash} ${circumference}`}
        strokeLinecap="round"
        style={{ transition: 'stroke-dasharray 0.9s ease-out' }}
      />
    </svg>
  )
}

// Pure SVG sparkline of cumulative ROI over the season
function Sparkline({ points, color, label }) {
  if (!points || points.length < 3) {
    return (
      <div className="flex items-center justify-center h-10 text-[10px] text-slate-600 font-mono">
        Not enough picks yet
      </div>
    )
  }

  const W = 300
  const H = 44
  const PAD = 2

  const rois = points.map(p => p.cumulative_roi)
  const rawMin = Math.min(...rois)
  const rawMax = Math.max(...rois)
  // Always show zero line; pad range slightly for breathing room
  const minY = Math.min(rawMin, -0.02) - 0.01
  const maxY = Math.max(rawMax,  0.02) + 0.01
  const rangeY = maxY - minY

  const toX = (i) => PAD + (i / (points.length - 1)) * (W - PAD * 2)
  const toY = (v) => H - PAD - ((v - minY) / rangeY) * (H - PAD * 2)

  const zeroY = toY(0)
  const lastX = toX(points.length - 1)
  const lastY = toY(rois[rois.length - 1])
  const isPositive = rois[rois.length - 1] >= 0

  const pathPts = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(p.cumulative_roi).toFixed(1)}`).join(' ')
  const areaPath = `${pathPts} L${lastX.toFixed(1)},${zeroY.toFixed(1)} L${PAD},${zeroY.toFixed(1)} Z`

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[9px] uppercase tracking-widest text-violet-400/40 font-semibold">{label}</span>
        <span className={`text-[10px] font-mono font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          {roi(rois[rois.length - 1])} ROI · {points[points.length - 1].wins}W–{points[points.length - 1].losses}L
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 44 }}>
        {/* Zero baseline */}
        <line
          x1={PAD} y1={zeroY} x2={W - PAD} y2={zeroY}
          stroke="rgba(139,92,246,0.15)" strokeWidth="0.8" strokeDasharray="3,3"
        />
        {/* Area fill */}
        <path d={areaPath} fill={`${color}14`} />
        {/* Line */}
        <path
          d={pathPts}
          fill="none"
          stroke={color}
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Endpoint dot */}
        <circle cx={lastX} cy={lastY} r="2.8" fill={color} />
        <circle cx={lastX} cy={lastY} r="5" fill={`${color}22`} />
      </svg>
    </div>
  )
}

function RecordRow({ label, record, accentColor }) {
  const isPositive = record.roi_at_110 != null && record.roi_at_110 > 0
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 border-b border-violet-50 dark:border-violet-500/[0.06] last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${accentColor}`} />
        <span className="text-[11px] font-medium text-slate-400 truncate">{label}</span>
      </div>
      {record.total === 0 ? (
        <span className="text-[11px] text-slate-600 font-mono">No picks</span>
      ) : (
        <div className="flex items-center gap-2.5 shrink-0">
          <span className="text-[11px] font-mono font-bold text-slate-200">
            {record.wins}–{record.losses}
          </span>
          <span className="text-[11px] font-mono text-slate-500">{fmt(record.win_pct)}</span>
          <span className={`text-[11px] font-mono font-semibold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {roi(record.roi_at_110)}
          </span>
        </div>
      )}
    </div>
  )
}

function YearBlock({ data, isCurrent }) {
  const combined = (data.model_picks.wins + data.yrfi_signal.wins)
  const combinedTotal = data.model_picks.total + data.yrfi_signal.total
  const combinedPct = combinedTotal > 0 ? combined / combinedTotal : null

  return (
    <div className="rounded-xl bg-white dark:bg-[#100e22] border border-violet-200 dark:border-violet-500/[0.12] p-4">
      <div className="flex items-center gap-3 mb-3">
        <WinArc winPct={combinedPct} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-gray-900 dark:text-slate-200 font-mono">{data.year}</span>
            {isCurrent && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-violet-500/[0.12] text-violet-400 ring-1 ring-violet-500/25 uppercase tracking-wide animate-pulse-glow">
                Live
              </span>
            )}
          </div>
          <p className="text-[10px] text-slate-500 font-mono mt-0.5">{data.total_games} games tracked</p>
        </div>
        <span className="ml-auto text-[10px] font-mono text-slate-600">
          {combinedPct != null ? `${(combinedPct * 100).toFixed(0)}% win` : ''}
        </span>
      </div>
      <RecordRow label="Model picks" record={data.model_picks} accentColor="bg-violet-500" />
      <RecordRow label="YRFI signal" record={data.yrfi_signal} accentColor="bg-sky-500" />
    </div>
  )
}

export default function SeasonStats({ stats, loading }) {
  const { trend } = usePickTrend()

  if (loading || !stats) return null

  const hasModelTrend = trend?.model_picks?.length >= 3
  const hasYrfiTrend  = trend?.yrfi_signal?.length >= 3

  return (
    <div className="mb-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[10px] uppercase tracking-widest font-semibold text-violet-500/60 dark:text-violet-400/40">
          Season Performance
        </span>
        <div className="flex-1 h-px bg-violet-200 dark:bg-violet-500/[0.10]" />
        <span className="text-[10px] font-mono text-violet-400/40 dark:text-violet-400/30">ROI at −110</span>
      </div>

      {/* Year blocks */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
        <YearBlock data={stats.current_year} isCurrent={true} />
        <YearBlock data={stats.prior_year}   isCurrent={false} />
      </div>

      {/* Sparklines — current season only, shown when there's enough data */}
      {(hasModelTrend || hasYrfiTrend) && (
        <div className="rounded-xl bg-white dark:bg-[#100e22] border border-violet-200 dark:border-violet-500/[0.12] px-4 py-3 space-y-3">
          {hasModelTrend && (
            <Sparkline
              points={trend.model_picks}
              color="rgb(139,92,246)"
              label={`${stats.current_year} Model Picks — Cumulative ROI`}
            />
          )}
          {hasModelTrend && hasYrfiTrend && (
            <div className="h-px bg-violet-500/[0.08]" />
          )}
          {hasYrfiTrend && (
            <Sparkline
              points={trend.yrfi_signal}
              color="rgb(56,189,248)"
              label={`${stats.current_year} YRFI Signal — Cumulative ROI`}
            />
          )}
        </div>
      )}
    </div>
  )
}
