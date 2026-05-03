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
  if (edge == null) return <span className="text-gray-400 dark:text-slate-500">—</span>
  let cls = 'text-gray-600 dark:text-slate-400'
  if (signal === 'yrfi_signal') cls = 'text-blue-600 dark:text-blue-400 font-bold'
  else if (signal === 'nrfi_strong') cls = 'text-green-600 dark:text-green-400 font-bold'
  else if (signal === 'nrfi_lean') cls = 'text-yellow-600 dark:text-yellow-500 font-semibold'
  else if (signal === 'yrfi_lean') cls = 'text-red-600 dark:text-red-400 font-semibold'
  else if (edge > 0) cls = 'text-yellow-600 dark:text-yellow-500'
  else if (edge < 0) cls = 'text-orange-600 dark:text-orange-400'
  return <span className={cls}>{fmtEdge(edge)}</span>
}

export default function GamesTable({ games, onSelect }) {
  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 dark:border-slate-800 shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 text-xs uppercase tracking-wide">
              <th className="text-left px-4 py-3 font-semibold">Matchup</th>
              <th className="px-4 py-3 font-semibold text-center">Signal</th>
              <th className="px-4 py-3 font-semibold text-center hidden sm:table-cell">Pitchers</th>
              <th className="px-4 py-3 font-semibold text-center">Model / Mkt</th>
              <th className="px-4 py-3 font-semibold text-center">Edge</th>
              <th className="px-4 py-3 font-semibold text-center hidden md:table-cell">Best Lines</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {games.map((game, i) => {
              const sig = getSignal(game.signal)
              const nrfi = bestOdds(game.bookmakers, 'nrfi')
              const yrfi = bestOdds(game.bookmakers, 'yrfi')
              const stripeBase = i % 2 === 0
                ? 'bg-white dark:bg-transparent'
                : 'bg-gray-50 dark:bg-slate-800/30'

              return (
                <tr
                  key={game.game_id}
                  onClick={() => onSelect(game)}
                  className={`${stripeBase} border-t border-gray-100 dark:border-slate-800/60 hover:bg-blue-50 dark:hover:bg-slate-700/40 cursor-pointer transition-colors group`}
                >
                  {/* Matchup */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className={`w-1 h-8 rounded-full shrink-0 ${sig.bar}`} />
                      <div>
                        <span className="font-bold text-gray-900 dark:text-white">
                          {game.away_team} <span className="font-normal text-gray-400 dark:text-slate-500">@</span> {game.home_team}
                        </span>
                        <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">
                          {game.game_time_et ? `${game.game_time_et} ET` : 'TBD'}
                        </p>
                      </div>
                    </div>
                  </td>

                  {/* Signal */}
                  <td className="px-4 py-3 text-center">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full whitespace-nowrap ${sig.badge}`}>
                      {sig.label}
                    </span>
                  </td>

                  {/* Pitchers */}
                  <td className="px-4 py-3 text-center hidden sm:table-cell">
                    <span className="text-gray-700 dark:text-slate-300 text-xs">
                      {lastName(game.away_sp?.name)} <span className="text-gray-300 dark:text-slate-600">vs</span> {lastName(game.home_sp?.name)}
                    </span>
                    <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">
                      {fmtEra(game.away_sp?.last5_era)} / {fmtEra(game.home_sp?.last5_era)} ERA
                    </p>
                  </td>

                  {/* Model / Market */}
                  <td className="px-4 py-3 text-center">
                    <span className="font-semibold text-gray-900 dark:text-white tabular-nums">
                      {pct(game.p_nrfi_model)}
                    </span>
                    <span className="text-gray-300 dark:text-slate-600 mx-1">/</span>
                    <span className="text-gray-500 dark:text-slate-400 tabular-nums">
                      {pct(game.p_nrfi_market)}
                    </span>
                  </td>

                  {/* Edge */}
                  <td className="px-4 py-3 text-center tabular-nums">
                    <EdgeCell edge={game.edge} signal={game.signal} />
                  </td>

                  {/* Best Lines */}
                  <td className="px-4 py-3 text-center hidden md:table-cell">
                    <div className="flex flex-col gap-0.5 items-center text-xs">
                      <span className="text-green-600 dark:text-green-400 font-mono">
                        N {fmtOdds(nrfi)}
                      </span>
                      <span className="text-blue-600 dark:text-blue-400 font-mono">
                        Y {fmtOdds(yrfi)}
                      </span>
                    </div>
                  </td>

                  {/* Expand arrow */}
                  <td className="pr-3 text-gray-300 dark:text-slate-600 group-hover:text-gray-500 dark:group-hover:text-slate-400 transition-colors">
                    ›
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
