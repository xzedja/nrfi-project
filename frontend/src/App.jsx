import { useState } from 'react'
import { useDashboard } from './hooks/useDashboard'
import Header from './components/Header'
import FilterTabs from './components/FilterTabs'
import GameCard from './components/GameCard'

function filterGames(games, active) {
  if (active === 'nrfi')    return games.filter(g => g.signal === 'nrfi_strong' || g.signal === 'nrfi_lean')
  if (active === 'yrfi')    return games.filter(g => g.signal === 'yrfi_signal' || g.signal === 'yrfi_slight' || g.signal === 'yrfi_lean')
  if (active === 'no_edge') return games.filter(g => g.signal === 'no_edge')
  return games
}

export default function App() {
  const { games, loading, error, lastUpdated, refresh } = useDashboard()
  const [activeFilter, setActiveFilter] = useState('all')

  const filtered = filterGames(games, activeFilter)

  const counts = {
    all:     games.length,
    nrfi:    games.filter(g => g.signal === 'nrfi_strong' || g.signal === 'nrfi_lean').length,
    yrfi:    games.filter(g => g.signal === 'yrfi_signal' || g.signal === 'yrfi_slight' || g.signal === 'yrfi_lean').length,
    no_edge: games.filter(g => g.signal === 'no_edge').length,
  }

  return (
    <div className="min-h-screen bg-[#020617] text-slate-100">
      <Header lastUpdated={lastUpdated} onRefresh={refresh} />

      <main className="max-w-7xl mx-auto px-4 py-6">
        <FilterTabs active={activeFilter} setActive={setActiveFilter} counts={counts} />

        {loading && (
          <div className="flex items-center justify-center py-32">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500" />
          </div>
        )}

        {error && (
          <div className="rounded-xl bg-red-950/50 border border-red-800/50 p-5 text-red-400 text-sm">
            <p className="font-semibold mb-1">Failed to load games</p>
            <p className="text-red-500/70">{error}</p>
            <button
              onClick={refresh}
              className="mt-3 text-xs px-3 py-1.5 rounded-md bg-red-900/50 hover:bg-red-900 transition-colors"
            >
              Try again
            </button>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-32 text-slate-600">
            <span className="text-5xl mb-4">⚾</span>
            <p className="text-lg font-semibold text-slate-500">No games to display</p>
            <p className="text-sm mt-1">
              {games.length === 0
                ? 'Run the daily pipeline to load today\'s games.'
                : 'No games match the selected filter.'}
            </p>
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {filtered.map(game => (
              <GameCard key={game.game_id} game={game} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
