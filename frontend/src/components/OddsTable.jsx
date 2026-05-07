import { fmtOdds, pct } from '../utils/signal'

export default function OddsTable({ bookmakers, signal }) {
  if (!bookmakers || bookmakers.length === 0) return null

  const nrfiFocus = signal === 'nrfi_strong' || signal === 'nrfi_lean'
  const yrfiFocus = signal === 'yrfi_signal' || signal === 'yrfi_slight' || signal === 'yrfi_lean'

  return (
    <div className="mx-4 mb-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] uppercase tracking-widest font-semibold text-violet-400/50 dark:text-violet-400/30">Lines</span>
        <div className="flex-1 h-px bg-violet-200 dark:bg-violet-500/[0.08]" />
      </div>

      <div className="rounded-lg overflow-hidden border border-violet-200 dark:border-violet-500/[0.12]">
        {/* Header */}
        <div className="grid grid-cols-[1fr_auto_auto_auto] bg-violet-50 dark:bg-violet-500/[0.05] border-b border-violet-100 dark:border-violet-500/[0.10]">
          <div className="px-3 py-1.5 text-[10px] uppercase tracking-widest text-violet-400/60 dark:text-violet-400/40 font-semibold">Book</div>
          <div className={`px-3 py-1.5 text-[10px] uppercase tracking-widest font-semibold text-center w-20 ${nrfiFocus ? 'text-emerald-500' : 'text-violet-400/40 dark:text-violet-400/30'}`}>NRFI</div>
          <div className={`px-3 py-1.5 text-[10px] uppercase tracking-widest font-semibold text-center w-20 ${yrfiFocus ? 'text-sky-500' : 'text-violet-400/40 dark:text-violet-400/30'}`}>YRFI</div>
          <div className="px-3 py-1.5 text-[10px] uppercase tracking-widest text-violet-400/40 dark:text-violet-400/30 font-semibold text-center w-14">Total</div>
        </div>

        {/* Rows */}
        {bookmakers.map((b) => {
          const isBest = (nrfiFocus && b.is_best_nrfi) || (yrfiFocus && b.is_best_yrfi)
          return (
            <div
              key={b.source}
              className={`
                grid grid-cols-[1fr_auto_auto_auto] border-t border-violet-100 dark:border-violet-500/[0.06]
                ${isBest
                  ? 'bg-violet-50/60 dark:bg-violet-500/[0.06]'
                  : 'bg-transparent hover:bg-violet-50/40 dark:hover:bg-violet-500/[0.03]'}
                transition-colors
              `}
            >
              {/* Book name */}
              <div className="px-3 py-2 flex items-center gap-1.5">
                {isBest && (
                  <span className="text-amber-400 text-[11px] leading-none">★</span>
                )}
                <span className={`text-xs ${isBest ? 'font-semibold text-gray-900 dark:text-slate-200' : 'text-gray-600 dark:text-slate-400'}`}>
                  {b.display_name}
                </span>
              </div>

              {/* NRFI */}
              <div className={`px-3 py-2 w-20 text-center ${b.is_best_nrfi ? 'text-emerald-400' : 'text-gray-500 dark:text-slate-500'}`}>
                <p className={`text-xs font-mono tabular-nums ${b.is_best_nrfi ? 'font-bold' : ''}`}>
                  {fmtOdds(b.nrfi_odds)}
                </p>
                {b.implied_nrfi_pct != null && (
                  <p className="text-[10px] font-mono text-slate-600 tabular-nums">{pct(b.implied_nrfi_pct)}</p>
                )}
              </div>

              {/* YRFI */}
              <div className={`px-3 py-2 w-20 text-center ${b.is_best_yrfi ? 'text-sky-400' : 'text-gray-500 dark:text-slate-500'}`}>
                <p className={`text-xs font-mono tabular-nums ${b.is_best_yrfi ? 'font-bold' : ''}`}>
                  {fmtOdds(b.yrfi_odds)}
                </p>
                {b.implied_yrfi_pct != null && (
                  <p className="text-[10px] font-mono text-slate-600 tabular-nums">{pct(b.implied_yrfi_pct)}</p>
                )}
              </div>

              {/* Total */}
              <div className="px-3 py-2 w-14 text-center text-xs font-mono text-slate-500 tabular-nums">
                {b.total ?? '—'}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
