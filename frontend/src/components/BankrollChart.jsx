function computeSeries(entries, filterFn, winFn) {
  const points = []
  let balance = 0
  for (const e of entries) {
    if (!filterFn(e)) continue
    balance = +(balance + (winFn(e) ? 1.0 : -1.1)).toFixed(2)
    points.push({ date: e.date, y: balance })
  }
  return points
}

const W = 700
const H = 200
const PAD = { t: 15, r: 20, b: 30, l: 48 }
const IW = W - PAD.l - PAD.r
const IH = H - PAD.t - PAD.b

export default function BankrollChart({ entries }) {
  if (!entries.length) return null

  const modelPts = computeSeries(
    entries,
    e => e.signal === 'nrfi_strong' || e.signal === 'nrfi_lean',
    e => e.nrfi_result === true,
  )
  const yrfiPts = computeSeries(
    entries,
    e => e.signal === 'yrfi_signal',
    e => e.nrfi_result === false,
  )

  if (!modelPts.length && !yrfiPts.length) {
    return <p className="text-slate-600 text-sm font-mono py-8 text-center">No picks in this period</p>
  }

  // Shared date-based x axis
  const allDates = [...new Set(entries.map(e => e.date))].sort()
  const tMin = new Date(allDates[0]).getTime()
  const tMax = new Date(allDates[allDates.length - 1]).getTime()
  const tRange = tMax - tMin || 1

  const toX = dateStr => PAD.l + ((new Date(dateStr).getTime() - tMin) / tRange) * IW

  const allY = [0, ...modelPts.map(p => p.y), ...yrfiPts.map(p => p.y)]
  const rawMin = Math.min(...allY)
  const rawMax = Math.max(...allY)
  const pad = (rawMax - rawMin) * 0.08 || 1
  const minY = rawMin - pad
  const maxY = rawMax + pad
  const yRange = maxY - minY

  const toY = y => PAD.t + (1 - (y - minY) / yRange) * IH
  const zeroY = toY(0)

  const makePath = (points, startDate) => {
    if (!points.length) return ''
    const start = `M ${toX(startDate)} ${toY(0)}`
    const rest = points.map(p => `L ${toX(p.date)} ${toY(p.y)}`).join(' ')
    return `${start} ${rest}`
  }

  const startDate = allDates[0]

  // Y axis ticks (5 levels)
  const yTicks = Array.from({ length: 5 }, (_, i) => {
    const v = minY + (yRange / 4) * i
    return { v, svgY: toY(v) }
  })

  // X axis labels (5 evenly spaced dates)
  const xLabels = Array.from({ length: 5 }, (_, i) => {
    const idx = Math.round((i / 4) * (allDates.length - 1))
    return allDates[idx]
  })

  const modelFinal = modelPts[modelPts.length - 1]?.y ?? 0
  const yrgiFinal = yrfiPts[yrfiPts.length - 1]?.y ?? 0

  return (
    <div className="space-y-3">
      {/* Legend */}
      <div className="flex flex-wrap gap-6 text-xs font-mono">
        {modelPts.length > 0 && (
          <span className="flex items-center gap-2">
            <span className="w-5 h-0.5 bg-emerald-500 inline-block rounded" />
            <span className="text-slate-500">Model Picks</span>
            <span className={`font-bold ${modelFinal >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {modelFinal >= 0 ? '+' : ''}{modelFinal.toFixed(1)}u
            </span>
            <span className="text-slate-600">({modelPts.length} bets)</span>
          </span>
        )}
        {yrfiPts.length > 0 && (
          <span className="flex items-center gap-2">
            <span className="w-5 h-0.5 bg-sky-500 inline-block rounded" />
            <span className="text-slate-500">YRFI Signal</span>
            <span className={`font-bold ${yrgiFinal >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {yrgiFinal >= 0 ? '+' : ''}{yrgiFinal.toFixed(1)}u
            </span>
            <span className="text-slate-600">({yrfiPts.length} bets)</span>
          </span>
        )}
      </div>

      {/* SVG chart */}
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {/* Grid lines + y labels */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD.l} y1={t.svgY} x2={W - PAD.r} y2={t.svgY}
              stroke="rgb(139,92,246)" strokeOpacity={0.07} strokeWidth={1}
            />
            <text
              x={PAD.l - 5} y={t.svgY + 4}
              textAnchor="end" fontSize={9}
              fill="rgb(148,163,184)" fillOpacity={0.5}
            >
              {t.v.toFixed(0)}
            </text>
          </g>
        ))}

        {/* Zero line */}
        <line
          x1={PAD.l} y1={zeroY} x2={W - PAD.r} y2={zeroY}
          stroke="rgb(139,92,246)" strokeOpacity={0.3} strokeWidth={1}
          strokeDasharray="4 3"
        />

        {/* X axis labels */}
        {xLabels.map((d, i) => (
          <text
            key={i}
            x={toX(d)} y={H - 5}
            textAnchor="middle" fontSize={9}
            fill="rgb(148,163,184)" fillOpacity={0.4}
          >
            {d.slice(5).replace('-', '/')}
          </text>
        ))}

        {/* YRFI line */}
        {yrfiPts.length > 0 && (
          <path
            d={makePath(yrfiPts, startDate)}
            fill="none" stroke="#38bdf8" strokeWidth={1.5} strokeLinejoin="round"
          />
        )}

        {/* Model line */}
        {modelPts.length > 0 && (
          <path
            d={makePath(modelPts, startDate)}
            fill="none" stroke="#34d399" strokeWidth={1.5} strokeLinejoin="round"
          />
        )}

        {/* End-point dots */}
        {modelPts.length > 0 && (
          <circle
            cx={toX(modelPts[modelPts.length - 1].date)}
            cy={toY(modelFinal)}
            r={3} fill="#34d399"
          />
        )}
        {yrfiPts.length > 0 && (
          <circle
            cx={toX(yrfiPts[yrfiPts.length - 1].date)}
            cy={toY(yrgiFinal)}
            r={3} fill="#38bdf8"
          />
        )}
      </svg>
    </div>
  )
}
