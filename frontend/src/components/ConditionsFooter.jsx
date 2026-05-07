export default function ConditionsFooter({ game }) {
  const chips = []

  if (game.is_dome) {
    chips.push({ label: 'Dome' })
  } else {
    if (game.temperature_f != null)
      chips.push({ label: `${Math.round(game.temperature_f)}°F` })

    if (game.wind_speed_mph != null) {
      const out = game.wind_out_mph ?? 0
      const dir = out > 2 ? '↗ out' : out < -2 ? '↙ in' : 'cross'
      chips.push({ label: `${Math.round(game.wind_speed_mph)} mph ${dir}` })
    }
  }

  if (game.park_factor != null)
    chips.push({ label: `Park ×${game.park_factor.toFixed(2)}` })

  if (game.ump_name) {
    const r = game.ump_nrfi_rate_above_avg
    const rate = r != null ? ` ${r >= 0 ? '+' : ''}${(r * 100).toFixed(1)}%` : ''
    chips.push({ label: `${game.ump_name}${rate}` })
  }

  if (chips.length === 0) return null

  return (
    <div className="px-4 py-2.5 border-t border-gray-100 dark:border-white/[0.04] flex flex-wrap gap-x-3 gap-y-1 bg-gray-50 dark:bg-white/[0.02]">
      {chips.map((c, i) => (
        <span key={i} className="text-[11px] font-mono text-gray-500 dark:text-slate-500">
          {c.label}
        </span>
      ))}
    </div>
  )
}
