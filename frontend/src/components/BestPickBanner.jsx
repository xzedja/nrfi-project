import { getSignal, pct, fmtOdds, fmtEdge } from '../utils/signal'

const _PRIORITY = { nrfi_strong: 0, yrfi_signal: 1, nrfi_lean: 2 }

function getBestPick(games) {
  const picks = games.filter(g => g.signal in _PRIORITY && !g.is_high_disagreement)
  if (!picks.length) return null
  return [...picks].sort((a, b) => {
    const pd = (_PRIORITY[a.signal] ?? 9) - (_PRIORITY[b.signal] ?? 9)
    if (pd !== 0) return pd
    return Math.abs(b.edge ?? 0) - Math.abs(a.edge ?? 0)
  })[0]
}

function lastName(name) {
  if (!name) return 'TBD'
  const parts = name.trim().split(' ')
  return parts.length > 1 ? parts[parts.length - 1] : name
}

function bestOddsVal(bookmakers, type) {
  const vals = bookmakers.map(b => type === 'nrfi' ? b.nrfi_odds : b.yrfi_odds).filter(v => v != null)
  return vals.length ? Math.max(...vals) : null
}

export default function BestPickBanner({ games }) {
  const pick = getBestPick(games)
  if (!pick) return null

  const sig = getSignal(pick.signal)
  const isYrfi = ['yrfi_signal', 'yrfi_slight', 'yrfi_lean'].includes(pick.signal)
  const odds = bestOddsVal(pick.bookmakers, isYrfi ? 'yrfi' : 'nrfi')

  return (
    <div className={`
      card-hover mb-5 rounded-xl overflow-hidden relative
      bg-white dark:bg-[#100e22]
      border border-violet-200 dark:border-violet-500/[0.12]
      border-l-4 ${sig.leftBar}
      shadow-sm dark:shadow-[0_4px_48px_rgba(109,40,217,0.13)]
    `}>
      {/* Shimmer sweep — dark mode only */}
      <div className="hidden dark:block shimmer-sweep" />

      {/* Header strip */}
      <div className="px-5 pt-3.5 pb-3 flex items-center gap-3 border-b border-violet-100 dark:border-violet-500/[0.08]">
        <span className="text-[10px] uppercase tracking-widest font-semibold text-violet-400/50 shrink-0">
          Top Pick
        </span>
        <div className="w-px h-3 bg-violet-200 dark:bg-violet-500/20" />
        <span className={`text-[11px] font-bold tracking-widest uppercase px-2.5 py-1 rounded-md ${sig.badge}`}>
          {sig.label}
        </span>
        <span className="ml-auto text-[11px] font-mono text-slate-500 tabular-nums shrink-0">
          {pick.game_time_et ? `${pick.game_time_et} ET` : 'TBD'}
        </span>
      </div>

      {/* Body */}
      <div className="px-5 py-4 flex items-center gap-5 flex-wrap">
        {/* Matchup */}
        <div className="flex items-baseline gap-2">
          <span className="text-[2rem] font-black tracking-tight text-gray-900 dark:text-white leading-none">
            {pick.away_team}
          </span>
          <span className="text-slate-500 text-sm font-mono">@</span>
          <span className="text-[2rem] font-black tracking-tight text-gray-900 dark:text-white leading-none">
            {pick.home_team}
          </span>
        </div>

        <div className="w-px h-10 bg-violet-100 dark:bg-violet-500/[0.10] hidden sm:block shrink-0" />

        {/* Pitchers + park */}
        <div className="hidden sm:block text-xs min-w-0">
          <p className="text-slate-400">
            {lastName(pick.away_sp?.name)}
            <span className="text-slate-600 mx-1">vs</span>
            {lastName(pick.home_sp?.name)}
          </p>
          {pick.park && <p className="text-slate-600 mt-0.5 truncate">{pick.park}</p>}
        </div>

        <div className="w-px h-10 bg-violet-100 dark:bg-violet-500/[0.10] hidden sm:block shrink-0" />

        {/* Key numbers */}
        <div className="flex items-center gap-5 font-mono ml-auto">
          <div className="text-center">
            <p className={`text-[1.6rem] font-black tabular-nums leading-none ${sig.edgeColor}`}>
              {fmtEdge(pick.edge)}
            </p>
            <p className="text-[10px] text-violet-400/45 uppercase tracking-widest mt-1">Edge</p>
          </div>
          <div className="text-center">
            <p className="text-[1.6rem] font-black tabular-nums leading-none text-slate-200">
              {pct(pick.p_nrfi_model)}
            </p>
            <p className="text-[10px] text-violet-400/45 uppercase tracking-widest mt-1">Model</p>
          </div>
          <div className="text-center">
            <p className="text-[1.6rem] font-black tabular-nums leading-none text-slate-500">
              {pct(pick.p_nrfi_market)}
            </p>
            <p className="text-[10px] text-violet-400/45 uppercase tracking-widest mt-1">Market</p>
          </div>
          {odds != null && (
            <div className="text-center">
              <p className={`text-[1.6rem] font-black tabular-nums leading-none ${isYrfi ? 'text-sky-400' : 'text-emerald-400'}`}>
                {fmtOdds(odds)}
              </p>
              <p className="text-[10px] text-violet-400/45 uppercase tracking-widest mt-1">Best Odds</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
