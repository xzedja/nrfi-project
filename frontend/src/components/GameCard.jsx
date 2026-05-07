import { getSignal, pct } from '../utils/signal'
import PitcherMatchup from './PitcherMatchup'
import ProbabilityBoxes from './ProbabilityBoxes'
import OddsTable from './OddsTable'
import ConditionsFooter from './ConditionsFooter'

function TeamStat({ label, away, home }) {
  return (
    <div className="grid grid-cols-3 text-xs py-1.5 border-b border-gray-100 dark:border-white/[0.04] last:border-0">
      <span className="text-gray-500 dark:text-slate-500 font-medium">{label}</span>
      <span className="text-center font-mono text-gray-700 dark:text-slate-300">{away ?? '—'}</span>
      <span className="text-center font-mono text-gray-700 dark:text-slate-300">{home ?? '—'}</span>
    </div>
  )
}

export default function GameCard({ game }) {
  const sig = getSignal(game.signal)

  const timeStr = game.game_time_et
    ? `${game.game_time_et} · ${game.game_time_ct} · ${game.game_time_pt}`
    : 'Time TBD'

  const fmtRate = (rec) => {
    if (!rec) return null
    return `${pct(rec.nrfi_rate)} (${rec.nrfi_wins}/${rec.total})`
  }

  return (
    <div className={`
      rounded-xl overflow-hidden flex flex-col
      bg-white dark:bg-[#0d1525]
      border border-gray-200 dark:border-white/[0.06]
      border-l-4 ${sig.leftBar}
      shadow-sm dark:shadow-none
    `}>

      {/* ── Top strip: badge + time ── */}
      <div className="px-4 pt-3.5 pb-3 flex items-center justify-between gap-3">
        <span className={`text-[11px] font-bold tracking-widest uppercase px-2.5 py-1 rounded-md ${sig.badge}`}>
          {sig.label}
        </span>
        <span className="text-[11px] font-mono text-slate-500 tabular-nums shrink-0">{timeStr}</span>
      </div>

      {/* ── Team matchup ── */}
      <div className="px-4 pb-4">
        <div className="flex items-center gap-0">
          {/* Away */}
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-0.5">Away</p>
            <p className="text-[2.6rem] font-black tracking-tight leading-none text-gray-900 dark:text-white truncate">
              {game.away_team}
            </p>
          </div>

          {/* VS divider */}
          <div className="px-3 flex flex-col items-center gap-1 shrink-0">
            <div className="w-px h-5 bg-gray-200 dark:bg-white/[0.06]" />
            <span className="text-[10px] font-mono font-bold text-gray-300 dark:text-slate-600 tracking-widest">VS</span>
            <div className="w-px h-5 bg-gray-200 dark:bg-white/[0.06]" />
          </div>

          {/* Home */}
          <div className="flex-1 min-w-0 text-right">
            <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-0.5">Home</p>
            <p className="text-[2.6rem] font-black tracking-tight leading-none text-gray-900 dark:text-white truncate">
              {game.home_team}
            </p>
          </div>
        </div>

        {game.park && (
          <p className="text-[11px] text-gray-400 dark:text-slate-600 mt-2 text-center truncate">{game.park}</p>
        )}
      </div>

      {/* ── Divider ── */}
      <div className="h-px bg-gray-100 dark:bg-white/[0.05] mx-4" />

      {/* ── Model / Market / Edge ── */}
      <ProbabilityBoxes
        pModel={game.p_nrfi_model}
        pMarket={game.p_nrfi_market}
        edge={game.edge}
        signal={game.signal}
        isHighDisagreement={game.is_high_disagreement}
      />

      {/* ── Team stats ── */}
      {(game.away_team_nrfi_current || game.home_team_nrfi_current || game.away_team_nrfi_prior || game.home_team_nrfi_prior) && (
        <>
          <div className="h-px bg-gray-100 dark:bg-white/[0.05] mx-4" />
          <div className="px-4 py-3">
            <div className="grid grid-cols-3 text-[10px] uppercase tracking-widest text-gray-400 dark:text-slate-500 pb-1.5 border-b border-gray-100 dark:border-white/[0.04] mb-0.5">
              <span />
              <span className="text-center font-semibold">{game.away_team}</span>
              <span className="text-center font-semibold">{game.home_team}</span>
            </div>
            {(game.away_team_nrfi_current || game.home_team_nrfi_current) && (
              <TeamStat
                label={`${game.away_team_nrfi_current?.year ?? game.home_team_nrfi_current?.year} NRFI`}
                away={fmtRate(game.away_team_nrfi_current)}
                home={fmtRate(game.home_team_nrfi_current)}
              />
            )}
            {(game.away_team_nrfi_prior || game.home_team_nrfi_prior) && (
              <TeamStat
                label={`${game.away_team_nrfi_prior?.year ?? game.home_team_nrfi_prior?.year} NRFI`}
                away={fmtRate(game.away_team_nrfi_prior)}
                home={fmtRate(game.home_team_nrfi_prior)}
              />
            )}
            <TeamStat
              label="1st Inn R/G"
              away={game.away_team_first_inn_rpg != null ? game.away_team_first_inn_rpg.toFixed(2) : null}
              home={game.home_team_first_inn_rpg != null ? game.home_team_first_inn_rpg.toFixed(2) : null}
            />
          </div>
        </>
      )}

      {/* ── Divider ── */}
      <div className="h-px bg-gray-100 dark:bg-white/[0.05] mx-4" />

      {/* ── Pitchers ── */}
      <PitcherMatchup awaySp={game.away_sp} homeSp={game.home_sp} />

      {/* ── YRFI signal callout ── */}
      {game.signal === 'yrfi_signal' && (
        <div className="mx-4 mb-3 rounded-lg bg-sky-950/50 border border-sky-800/40 px-3.5 py-2.5">
          <p className="text-sky-400 text-xs font-bold tracking-wide mb-0.5">YRFI SIGNAL ACTIVE</p>
          <p className="text-sky-500/70 text-[11px] leading-relaxed">
            Market implies ≥60% NRFI · historically +46–54% ROI betting YRFI (2023–2024, 2,700+ bets)
          </p>
        </div>
      )}

      {/* ── Odds ── */}
      <OddsTable bookmakers={game.bookmakers} signal={game.signal} />

      {/* ── Conditions ── */}
      <ConditionsFooter game={game} />
    </div>
  )
}
