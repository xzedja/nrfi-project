import { useState, useEffect } from 'react'
import { useDashboard } from './hooks/useDashboard'
import { useSeasonStats } from './hooks/useSeasonStats'
import Header from './components/Header'
import FilterTabs from './components/FilterTabs'
import GameCard from './components/GameCard'
import GamesTable from './components/GamesTable'
import GameModal from './components/GameModal'
import SeasonStats from './components/SeasonStats'

function filterGames(games, active) {
  if (active === 'nrfi')    return games.filter(g => g.signal === 'nrfi_strong' || g.signal === 'nrfi_lean')
  if (active === 'yrfi')    return games.filter(g => g.signal === 'yrfi_signal' || g.signal === 'yrfi_slight' || g.signal === 'yrfi_lean')
  if (active === 'no_edge') return games.filter(g => g.signal === 'no_edge')
  return games
}

export default function App() {
  const { games, loading, error, lastUpdated, refresh } = useDashboard()
  const { stats: seasonStats, loading: statsLoading } = useSeasonStats()
  const [activeFilter, setActiveFilter] = useState('all')
  const [viewMode, setViewMode] = useState(() => localStorage.getItem('nrfi-view') || 'tile')
  const [theme, setTheme]       = useState(() => localStorage.getItem('nrfi-theme') || 'dark')
  const [selectedGame, setSelectedGame] = useState(null)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
    localStorage.setItem('nrfi-theme', theme)
  }, [theme])

  useEffect(() => {
    localStorage.setItem('nrfi-view', viewMode)
  }, [viewMode])

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  const filtered = filterGames(games, activeFilter)

  const counts = {
    all:     games.length,
    nrfi:    games.filter(g => g.signal === 'nrfi_strong' || g.signal === 'nrfi_lean').length,
    yrfi:    games.filter(g => g.signal === 'yrfi_signal' || g.signal === 'yrfi_slight' || g.signal === 'yrfi_lean').length,
    no_edge: games.filter(g => g.signal === 'no_edge').length,
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-[#020617] text-gray-900 dark:text-slate-100">
      <Header
        lastUpdated={lastUpdated}
        onRefresh={refresh}
        theme={theme}
        toggleTheme={toggleTheme}
        viewMode={viewMode}
        setViewMode={setViewMode}
      />

      <main className="max-w-7xl mx-auto px-4 py-6">
        <SeasonStats stats={seasonStats} loading={statsLoading} />

        <FilterTabs active={activeFilter} setActive={setActiveFilter} counts={counts} />

        {loading && (
          <div className="flex items-center justify-center py-32">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500" />
          </div>
        )}

        {error && (
          <div className="rounded-xl bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-800/50 p-5 text-red-600 dark:text-red-400 text-sm">
            <p className="font-semibold mb-1">Failed to load games</p>
            <p className="text-red-400">{error}</p>
            <button
              onClick={refresh}
              className="mt-3 text-xs px-3 py-1.5 rounded-md bg-red-100 dark:bg-red-900/50 hover:bg-red-200 dark:hover:bg-red-900 transition-colors"
            >
              Try again
            </button>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-32 text-gray-400 dark:text-slate-600">
            <span className="text-5xl mb-4">⚾</span>
            <p className="text-lg font-semibold text-gray-500 dark:text-slate-500">No games to display</p>
            <p className="text-sm mt-1">
              {games.length === 0
                ? "Run the daily pipeline to load today's games."
                : 'No games match the selected filter.'}
            </p>
          </div>
        )}

        {!loading && !error && filtered.length > 0 && viewMode === 'tile' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {filtered.map(game => (
              <GameCard key={game.game_id} game={game} />
            ))}
          </div>
        )}

        {!loading && !error && filtered.length > 0 && viewMode === 'table' && (
          <GamesTable games={filtered} onSelect={setSelectedGame} />
        )}
      </main>

      {selectedGame && (
        <GameModal game={selectedGame} onClose={() => setSelectedGame(null)} />
      )}
    </div>
  )
}
