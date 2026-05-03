export default function ConditionsFooter({ game }) {
  const chips = []

  if (game.is_dome) {
    chips.push({ icon: '🏟️', text: 'Dome / Retractable Roof' })
  } else {
    if (game.temperature_f != null)
      chips.push({ icon: '🌡️', text: `${Math.round(game.temperature_f)}°F` })

    if (game.wind_speed_mph != null) {
      const out = game.wind_out_mph ?? 0
      const dir = out > 2 ? ' out ↗' : out < -2 ? ' in ↙' : ' cross'
      chips.push({ icon: '💨', text: `${Math.round(game.wind_speed_mph)} mph${dir}` })
    }
  }

  if (game.park_factor != null)
    chips.push({ icon: '🏟', text: `Park ${game.park_factor.toFixed(2)}` })

  if (game.ump_name) {
    const r = game.ump_nrfi_rate_above_avg
    const rate = r != null ? ` · ${r >= 0 ? '+' : ''}${(r * 100).toFixed(1)}% NRFI` : ''
    chips.push({ icon: '👤', text: `${game.ump_name}${rate}` })
  }

  if (chips.length === 0) return null

  return (
    <div className="px-5 py-3 border-t border-gray-100 dark:border-slate-800 flex flex-wrap gap-x-5 gap-y-1 bg-gray-50 dark:bg-slate-800/20">
      {chips.map((c, i) => (
        <span key={i} className="text-xs text-gray-500 dark:text-slate-500 flex items-center gap-1">
          <span>{c.icon}</span>
          <span>{c.text}</span>
        </span>
      ))}
    </div>
  )
}
