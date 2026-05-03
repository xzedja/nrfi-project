import { fmtOdds } from '../utils/signal'

export default function OddsTable({ bookmakers, signal }) {
  if (!bookmakers || bookmakers.length === 0) return null

  const nrfiFocus = signal === 'nrfi_strong' || signal === 'nrfi_lean'
  const yrfiFocus = signal === 'yrfi_signal' || signal === 'yrfi_slight' || signal === 'yrfi_lean'

  return (
    <div className="mx-5 mb-4">
      <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Sportsbook Lines</p>
      <div className="rounded-xl overflow-hidden border border-slate-800">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-800/80 text-slate-400">
              <th className="text-left px-3 py-2 font-medium">Book</th>
              <th className={`px-3 py-2 font-medium text-center ${nrfiFocus ? 'text-green-400' : ''}`}>
                NRFI
              </th>
              <th className={`px-3 py-2 font-medium text-center ${yrfiFocus ? 'text-blue-400' : ''}`}>
                YRFI
              </th>
              <th className="px-3 py-2 font-medium text-center text-slate-500">Total</th>
            </tr>
          </thead>
          <tbody>
            {bookmakers.map((b, i) => {
              const isBest = (nrfiFocus && b.is_best_nrfi) || (yrfiFocus && b.is_best_yrfi)
              return (
                <tr
                  key={b.source}
                  className={`border-t border-slate-800/60 ${isBest ? 'bg-slate-700/30' : i % 2 === 0 ? '' : 'bg-slate-800/20'}`}
                >
                  <td className="px-3 py-2 text-slate-300 font-medium">
                    {isBest && <span className="text-yellow-400 mr-1">★</span>}
                    {b.display_name}
                  </td>
                  <td className={`px-3 py-2 text-center font-mono tabular-nums ${b.is_best_nrfi ? 'text-green-400 font-bold' : 'text-slate-400'}`}>
                    {fmtOdds(b.nrfi_odds)}
                  </td>
                  <td className={`px-3 py-2 text-center font-mono tabular-nums ${b.is_best_yrfi ? 'text-blue-400 font-bold' : 'text-slate-400'}`}>
                    {fmtOdds(b.yrfi_odds)}
                  </td>
                  <td className="px-3 py-2 text-center text-slate-500 tabular-nums">
                    {b.total ?? '—'}
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
