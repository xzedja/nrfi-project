import { useState, useEffect } from 'react'
import { useHistoryGames } from '../hooks/useHistoryGames'
import GameCard from './GameCard'
import GamesTable from './GamesTable'
import GameModal from './GameModal'
import FilterTabs from './FilterTabs'

function filterGames(games, active) {
  if (active === 'nrfi') return games.filter(g => g.signal === 'nrfi_strong' || g.signal === 'nrfi_lean')
  if (active === 'yrfi') return games.filter(g => g.signal === 'yrfi_signal' || g.signal === 'yrfi_slight' || g.signal === 'yrfi_lean')
  if (active === 'no_edge') return games.filter(g => g.signal === 'no_edge')
  return games
}

function isoYesterday() {
  const d = new Date(Date.now() - 86400000)
  return d.toISOString().split('T')[0]
}

const _NRFI_SIGS = new Set(['nrfi_strong', 'nrfi_lean'])
const _YRFI_SIGS = new Set(['yrfi_signal'])

export default function HistoryView({ viewMode }) {
  const yesterday = isoYesterday()
  const [selectedDate, setSelectedDate] = useState(yesterday)
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedGame, setSelectedGame] = useState(null)
  const { games, loading, error, load } = useHistoryGames()

  useEffect(() => { load(selectedDate) }, [selectedDate, load])

  const filtered = filterGames(games, activeFilter)
  const counts = {
    all:     games.length,
    nrfi:    games.filter(g => _NRFI_SIGS.has(g.signal)).length,
    yrfi:    games.filter(g => g.signal === 'yrfi_signal' || g.signal === 'yrfi_slight' || g.signal === 'yrfi_lean').length,
    no_edge: games.filter(g => g.signal === 'no_edge').length,
  }

  // Day record for signal picks with known results
  const picks = games.filter(g => (_NRFI_SIGS.has(g.signal) || _YRFI_SIGS.has(g.signal)) && g.nrfi_result !== null && g.nrfi_result !== undefined)
  const wins = picks.filter(g => _NRFI_SIGS.has(g.signal) ? g.nrfi_result === true : g.nrfi_result === false).length
  const losses = picks.length - wins

  return (
    <div>
      {/* Controls row */}
      <div className="flex items-center gap-4 mb-5 flex-wrap">
        <input
          type="date"
          value={selectedDate}
          max={yesterday}
          onChange={e => setSelectedDate(e.target.value)}
          className="h-8 px-3 rounded-lg text-sm font-mono bg-violet-500/[0.05] border border-violet-200 dark:border-violet-500/[0.15] text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-1 focus:ring-violet-500/40"
        />
        {picks.length > 0 && !loading && (
          <div className="flex items-center gap-2 font-mono text-sm">
            <span className="text-emerald-400 font-bold">{wins}W</span>
            <span className="text-slate-600">–</span>
            <span className="text-red-400 font-bold">{losses}L</span>
            <span className="text-slate-500 text-xs">
              ({((wins / picks.length) * 100).toFixed(0)}% on {picks.length} picks)
            </span>
          </div>
        )}
      </div>

      <FilterTabs active={activeFilter} setActive={setActiveFilter} counts={counts} />

      {loading && (
        <div className="flex justify-center py-20 gap-3">
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.3s]" />
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.15s]" />
          <div className="w-2 h-2 rounded-full bg-slate-500 animate-bounce" />
        </div>
      )}

      {error && (
        <div className="rounded-xl bg-red-950/40 border border-red-800/40 p-5 text-red-400 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-slate-600">
          <span className="text-5xl mb-4 opacity-30">⚾</span>
          <p className="text-base font-semibold text-slate-500">No games found for this date</p>
        </div>
      )}

      {!loading && !error && filtered.length > 0 && viewMode === 'tile' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {filtered.map(game => <GameCard key={game.game_id} game={game} />)}
        </div>
      )}

      {!loading && !error && filtered.length > 0 && viewMode === 'table' && (
        <GamesTable games={filtered} onSelect={setSelectedGame} />
      )}

      {selectedGame && (
        <GameModal game={selectedGame} onClose={() => setSelectedGame(null)} />
      )}
    </div>
  )
}
