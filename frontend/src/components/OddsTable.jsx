import { fmtOdds, pct } from '../utils/signal'

export default function OddsTable({ bookmakers, signal }) {
  if (!bookmakers || bookmakers.length === 0) return null

  const nrfiFocus = signal === 'nrfi_strong' || signal === 'nrfi_lean'
  const yrfiFocus = signal === 'yrfi_signal' || signal === 'yrfi_slight' || signal === 'yrfi_lean'

  return (
    <div className="mx-5 mb-4">
      <p className="text-xs text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2">Sportsbook Lines</p>
      <div className="rounded-xl overflow-hidden border border-gray-200 dark:border-slate-800">
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[280px]">
            <thead>
              <tr className="bg-gray-100 dark:bg-slate-800/80 text-gray-500 dark:text-slate-400">
                <th className="text-left px-3 py-2 font-medium">Book</th>
                <th className={`px-3 py-2 font-medium text-center ${nrfiFocus ? 'text-green-600 dark:text-green-400' : ''}`}>
                  NRFI
                </th>
                <th className={`px-3 py-2 font-medium text-center ${yrfiFocus ? 'text-blue-600 dark:text-blue-400' : ''}`}>
                  YRFI
                </th>
                <th className="px-3 py-2 font-medium text-center text-gray-400 dark:text-slate-500">Total</th>
              </tr>
            </thead>
            <tbody>
              {bookmakers.map((b, i) => {
                const isBest = (nrfiFocus && b.is_best_nrfi) || (yrfiFocus && b.is_best_yrfi)
                return (
                  <tr
                    key={b.source}
                    className={`border-t border-gray-100 dark:border-slate-800/60 ${
                      isBest
                        ? 'bg-gray-100 dark:bg-slate-700/30'
                        : i % 2 === 0 ? '' : 'bg-gray-50/50 dark:bg-slate-800/20'
                    }`}
                  >
                    <td className="px-3 py-2 text-gray-700 dark:text-slate-300 font-medium">
                      {isBest && <span className="text-yellow-500 dark:text-yellow-400 mr-1">★</span>}
                      {b.display_name}
                    </td>
                    <td className={`px-3 py-2 text-center ${
                      b.is_best_nrfi ? 'text-green-600 dark:text-green-400' : 'text-gray-500 dark:text-slate-400'
                    }`}>
                      <div className="flex flex-col items-center gap-0.5">
                        <span className={`font-mono tabular-nums ${b.is_best_nrfi ? 'font-bold' : ''}`}>
                          {fmtOdds(b.nrfi_odds)}
                        </span>
                        {b.implied_nrfi_pct != null && (
                          <span className="text-[10px] tabular-nums text-gray-400 dark:text-slate-500">
                            {pct(b.implied_nrfi_pct)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className={`px-3 py-2 text-center ${
                      b.is_best_yrfi ? 'text-blue-600 dark:text-blue-400' : 'text-gray-500 dark:text-slate-400'
                    }`}>
                      <div className="flex flex-col items-center gap-0.5">
                        <span className={`font-mono tabular-nums ${b.is_best_yrfi ? 'font-bold' : ''}`}>
                          {fmtOdds(b.yrfi_odds)}
                        </span>
                        {b.implied_yrfi_pct != null && (
                          <span className="text-[10px] tabular-nums text-gray-400 dark:text-slate-500">
                            {pct(b.implied_yrfi_pct)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-center text-gray-400 dark:text-slate-500 tabular-nums">
                      {b.total ?? '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
