import { getSignal } from '../utils/signal'
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
        <div className="flex items-center gap-3 mb-1">
          <span className="text-3xl font-black tracking-tight text-gray-900 dark:text-white">{game.away_team}</span>
          <span className="text-gray-300 dark:text-slate-600 text-xl font-thin">@</span>
          <span className="text-3xl font-black tracking-tight text-gray-900 dark:text-white">{game.home_team}</span>
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-400 dark:text-slate-500">
          <span>
            1st Inn R/G:&nbsp;
            <span className="text-gray-700 dark:text-slate-300 font-medium">
              {game.away_team_first_inn_rpg != null ? game.away_team_first_inn_rpg.toFixed(2) : '—'}
            </span>
            <span className="text-gray-300 dark:text-slate-600"> (away)</span>
          </span>
          <span className="text-gray-200 dark:text-slate-700">·</span>
          <span>
            <span className="text-gray-700 dark:text-slate-300 font-medium">
              {game.home_team_first_inn_rpg != null ? game.home_team_first_inn_rpg.toFixed(2) : '—'}
            </span>
            <span className="text-gray-300 dark:text-slate-600"> (home)</span>
          </span>
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
