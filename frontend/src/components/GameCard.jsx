import { getSignal, pct } from '../utils/signal'
import PitcherMatchup from './PitcherMatchup'
import ProbabilityBoxes from './ProbabilityBoxes'
import OddsTable from './OddsTable'
import ConditionsFooter from './ConditionsFooter'

export default function GameCard({ game }) {
  const sig = getSignal(game.signal)

  const timeStr = game.game_time_et
    ? `${game.game_time_et} ET · ${game.game_time_ct} CT · ${game.game_time_pt} PT`
    : 'Time TBD'

  return (
    <div className={`rounded-2xl overflow-hidden bg-white dark:bg-slate-900 border border-gray-100 dark:border-transparent border-t-4 ${sig.border} shadow-md dark:shadow-xl flex flex-col`}>

      {/* Header */}
      <div className="px-5 pt-4 pb-3 flex items-start justify-between gap-4">
        <div>
          <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${sig.badge}`}>
            {sig.label}
          </span>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">{timeStr}</p>
        </div>
        {game.park && (
          <p className="text-xs text-gray-400 dark:text-slate-600 text-right leading-snug max-w-[140px]">
            {game.park}
          </p>
        )}
      </div>

      {/* Teams + 1st inn offense */}
      <div className="px-5 pb-4">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-3xl font-black tracking-tight text-gray-900 dark:text-white">{game.away_team}</span>
          <span className="text-gray-300 dark:text-slate-600 text-xl font-thin">@</span>
          <span className="text-3xl font-black tracking-tight text-gray-900 dark:text-white">{game.home_team}</span>
        </div>

        {/* Team NRFI stats mini-table */}
        <div className="rounded-lg bg-gray-50 dark:bg-slate-800/40 border border-gray-100 dark:border-slate-800 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-400 dark:text-slate-500 border-b border-gray-100 dark:border-slate-800">
                <th className="text-left px-3 py-1.5 font-medium w-[30%]"></th>
                <th className="text-center px-2 py-1.5 font-medium">{game.away_team}</th>
                <th className="text-center px-2 py-1.5 font-medium">{game.home_team}</th>
              </tr>
            </thead>
            <tbody>
              {[game.away_team_nrfi_current, game.home_team_nrfi_current].some(Boolean) && (
                <tr className="border-b border-gray-100 dark:border-slate-800/60">
                  <td className="px-3 py-1.5 text-gray-400 dark:text-slate-500 font-medium">
                    {game.away_team_nrfi_current?.year ?? game.home_team_nrfi_current?.year} NRFI
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {game.away_team_nrfi_current
                      ? <><span className="font-semibold text-gray-700 dark:text-slate-300">{pct(game.away_team_nrfi_current.nrfi_rate)}</span>
                         <span className="text-gray-400 dark:text-slate-500 ml-1">({game.away_team_nrfi_current.nrfi_wins}/{game.away_team_nrfi_current.total})</span></>
                      : <span className="text-gray-300 dark:text-slate-600">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {game.home_team_nrfi_current
                      ? <><span className="font-semibold text-gray-700 dark:text-slate-300">{pct(game.home_team_nrfi_current.nrfi_rate)}</span>
                         <span className="text-gray-400 dark:text-slate-500 ml-1">({game.home_team_nrfi_current.nrfi_wins}/{game.home_team_nrfi_current.total})</span></>
                      : <span className="text-gray-300 dark:text-slate-600">—</span>}
                  </td>
                </tr>
              )}
              {[game.away_team_nrfi_prior, game.home_team_nrfi_prior].some(Boolean) && (
                <tr className="border-b border-gray-100 dark:border-slate-800/60">
                  <td className="px-3 py-1.5 text-gray-400 dark:text-slate-500 font-medium">
                    {game.away_team_nrfi_prior?.year ?? game.home_team_nrfi_prior?.year} NRFI
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {game.away_team_nrfi_prior
                      ? <><span className="font-semibold text-gray-700 dark:text-slate-300">{pct(game.away_team_nrfi_prior.nrfi_rate)}</span>
                         <span className="text-gray-400 dark:text-slate-500 ml-1">({game.away_team_nrfi_prior.nrfi_wins}/{game.away_team_nrfi_prior.total})</span></>
                      : <span className="text-gray-300 dark:text-slate-600">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {game.home_team_nrfi_prior
                      ? <><span className="font-semibold text-gray-700 dark:text-slate-300">{pct(game.home_team_nrfi_prior.nrfi_rate)}</span>
                         <span className="text-gray-400 dark:text-slate-500 ml-1">({game.home_team_nrfi_prior.nrfi_wins}/{game.home_team_nrfi_prior.total})</span></>
                      : <span className="text-gray-300 dark:text-slate-600">—</span>}
                  </td>
                </tr>
              )}
              <tr>
                <td className="px-3 py-1.5 text-gray-400 dark:text-slate-500 font-medium">1st Inn R/G</td>
                <td className="px-2 py-1.5 text-center font-semibold text-gray-700 dark:text-slate-300 tabular-nums">
                  {game.away_team_first_inn_rpg != null ? game.away_team_first_inn_rpg.toFixed(2) : '—'}
                </td>
                <td className="px-2 py-1.5 text-center font-semibold text-gray-700 dark:text-slate-300 tabular-nums">
                  {game.home_team_first_inn_rpg != null ? game.home_team_first_inn_rpg.toFixed(2) : '—'}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Pitchers */}
      <PitcherMatchup awaySp={game.away_sp} homeSp={game.home_sp} />

      {/* Model / Market / Edge */}
      <ProbabilityBoxes
        pModel={game.p_nrfi_model}
        pMarket={game.p_nrfi_market}
        edge={game.edge}
        isHighDisagreement={game.is_high_disagreement}
      />

      {/* YRFI Signal callout */}
      {game.signal === 'yrfi_signal' && (
        <div className="mx-5 mb-4 rounded-xl bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-800/50 p-3">
          <p className="text-blue-700 dark:text-blue-300 text-sm font-semibold mb-0.5">🔵 YRFI Signal Active</p>
          <p className="text-blue-600/80 dark:text-blue-400/70 text-xs leading-relaxed">
            Market implies ≥60% NRFI — historical edge favors YRFI.
            Backtested +46–54% ROI (2023–2024, 2,700+ bets).
          </p>
        </div>
      )}

      {/* Sportsbook odds */}
      <OddsTable bookmakers={game.bookmakers} signal={game.signal} />

      {/* Conditions */}
      <ConditionsFooter game={game} />
    </div>
  )
}
