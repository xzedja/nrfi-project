import { getSignal, fmtEdge, pct, fmtOdds, fmtEra } from '../utils/signal'

function lastName(name) {
  if (!name) return 'TBD'
  const parts = name.trim().split(' ')
  return parts.length > 1 ? parts[parts.length - 1] : name
}

function bestOdds(bookmakers, type) {
  const vals = bookmakers
    .map(b => type === 'nrfi' ? b.nrfi_odds : b.yrfi_odds)
    .filter(v => v != null)
  return vals.length ? Math.max(...vals) : null
}

function EdgeCell({ edge, signal }) {
  if (edge == null) return <span className="text-slate-600">—</span>
  let cls = 'text-slate-500'
  if (signal === 'yrfi_signal')  cls = 'text-sky-400 font-bold'
  else if (signal === 'nrfi_strong') cls = 'text-emerald-400 font-bold'
  else if (signal === 'nrfi_lean') cls = 'text-amber-400 font-semibold'
  else if (signal === 'yrfi_lean') cls = 'text-red-400 font-semibold'
  else if (edge > 0) cls = 'text-amber-500/70'
  else if (edge < 0) cls = 'text-orange-500/70'
  return <span className={`font-mono tabular-nums ${cls}`}>{fmtEdge(edge)}</span>
}

export default function GamesTable({ games, onSelect }) {
  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 dark:border-white/[0.06]">
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="bg-gray-50 dark:bg-white/[0.03] border-b border-gray-200 dark:border-white/[0.06] text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
              <th className="text-left px-4 py-3">Matchup</th>
              <th className="px-4 py-3 text-center">Signal</th>
              <th className="px-4 py-3 text-center hidden sm:table-cell">Pitchers</th>
              <th className="px-4 py-3 text-center">Model / Mkt</th>
              <th className="px-4 py-3 text-center">Edge</th>
              <th className="px-4 py-3 text-center hidden md:table-cell">Best Lines</th>
              <th className="w-6" />
            </tr>
          </thead>
          <tbody>
            {games.map((game, i) => {
              const sig = getSignal(game.signal)
              const nrfi = bestOdds(game.bookmakers, 'nrfi')
              const yrfi = bestOdds(game.bookmakers, 'yrfi')

              return (
                <tr
                  key={game.game_id}
                  onClick={() => onSelect(game)}
                  className={`
                    border-t border-gray-100 dark:border-white/[0.04]
                    hover:bg-gray-50 dark:hover:bg-white/[0.03]
                    cursor-pointer transition-colors group
                    ${i % 2 === 0 ? '' : 'bg-gray-50/40 dark:bg-white/[0.01]'}
                  `}
                >
                  {/* Matchup */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className={`w-0.5 h-7 rounded-full shrink-0 ${sig.bar}`} />
                      <div>
                        <span className="font-bold text-gray-900 dark:text-slate-100">
                          {game.away_team}
                          <span className="font-normal text-slate-500 mx-1.5">@</span>
                          {game.home_team}
                        </span>
                        <p className="text-[11px] font-mono text-slate-500 mt-0.5">
                          {game.game_time_et ? `${game.game_time_et} ET` : 'TBD'}
                        </p>
                      </div>
                    </div>
                  </td>

                  {/* Signal */}
                  <td className="px-4 py-3 text-center">
                    <span className={`text-[10px] font-bold px-2.5 py-1 rounded-md tracking-wider ${sig.badge}`}>
                      {sig.label}
                    </span>
                  </td>

                  {/* Pitchers */}
                  <td className="px-4 py-3 text-center hidden sm:table-cell">
                    <span className="text-xs text-slate-300">
                      {lastName(game.away_sp?.name)}
                      <span className="text-slate-600 mx-1">vs</span>
                      {lastName(game.home_sp?.name)}
                    </span>
                    <p className="text-[11px] font-mono text-slate-500 mt-0.5">
                      {fmtEra(game.away_sp?.last5_era)} / {fmtEra(game.home_sp?.last5_era)} ERA
                    </p>
                  </td>

                  {/* Model / Market */}
                  <td className="px-4 py-3 text-center">
                    <span className="font-mono font-semibold text-slate-200 tabular-nums">{pct(game.p_nrfi_model)}</span>
                    <span className="text-slate-600 mx-1">/</span>
                    <span className="font-mono text-slate-500 tabular-nums">{pct(game.p_nrfi_market)}</span>
                  </td>

                  {/* Edge */}
                  <td className="px-4 py-3 text-center">
                    <EdgeCell edge={game.edge} signal={game.signal} />
                  </td>

                  {/* Best Lines */}
                  <td className="px-4 py-3 text-center hidden md:table-cell">
                    <div className="flex flex-col items-center gap-0.5">
                      <span className="text-[11px] font-mono text-emerald-500">N {fmtOdds(nrfi)}</span>
                      <span className="text-[11px] font-mono text-sky-500">Y {fmtOdds(yrfi)}</span>
                    </div>
                  </td>

                  {/* Arrow */}
                  <td className="pr-3 text-slate-600 group-hover:text-slate-400 transition-colors text-sm">›</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
