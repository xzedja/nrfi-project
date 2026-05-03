function GridIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-4 h-4">
      <rect x="1" y="1" width="6" height="6" rx="1" />
      <rect x="9" y="1" width="6" height="6" rx="1" />
      <rect x="1" y="9" width="6" height="6" rx="1" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </svg>
  )
}

function ListIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-4 h-4">
      <rect x="1" y="2" width="14" height="2.5" rx="1" />
      <rect x="1" y="6.75" width="14" height="2.5" rx="1" />
      <rect x="1" y="11.5" width="14" height="2.5" rx="1" />
    </svg>
  )
}

export default function Header({ lastUpdated, onRefresh, theme, toggleTheme, viewMode, setViewMode }) {
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  })
  const timeStr = lastUpdated
    ? lastUpdated.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    : '—'

  const btnBase = 'p-2 transition-colors rounded-md'
  const btnActive = 'bg-gray-200 dark:bg-slate-700 text-gray-900 dark:text-white'
  const btnInactive = 'bg-transparent text-gray-400 dark:text-slate-500 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-700 dark:hover:text-slate-300'

  return (
    <header className="border-b border-gray-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur sticky top-0 z-20">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-base sm:text-lg font-black tracking-tight text-gray-900 dark:text-white">
            ⚾ NRFI Dashboard
          </h1>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5 hidden sm:block">{today}</p>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
          <span className="text-xs text-gray-400 dark:text-slate-600 hidden md:block mr-1">
            Updated {timeStr}
          </span>

          {/* View mode toggle */}
          <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800">
            <button
              onClick={() => setViewMode('tile')}
              title="Card view"
              className={`${btnBase} ${viewMode === 'tile' ? btnActive : btnInactive}`}
            >
              <GridIcon />
            </button>
            <button
              onClick={() => setViewMode('table')}
              title="Table view"
              className={`${btnBase} ${viewMode === 'table' ? btnActive : btnInactive}`}
            >
              <ListIcon />
            </button>
          </div>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className={`${btnBase} border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-700`}
          >
            {theme === 'dark' ? (
              <svg viewBox="0 0 16 16" fill="currentColor" className="w-4 h-4">
                <path d="M8 12A4 4 0 1 0 8 4a4 4 0 0 0 0 8zm0 1.5a5.5 5.5 0 1 1 0-11 5.5 5.5 0 0 1 0 11zM8 1a.75.75 0 0 1 .75.75v.5a.75.75 0 0 1-1.5 0v-.5A.75.75 0 0 1 8 1zm0 12a.75.75 0 0 1 .75.75v.5a.75.75 0 0 1-1.5 0v-.5A.75.75 0 0 1 8 13zm5.657-9.657a.75.75 0 0 1 0 1.06l-.354.354a.75.75 0 1 1-1.06-1.06l.353-.354a.75.75 0 0 1 1.06 0zm-9.9 9.9a.75.75 0 0 1 0 1.06l-.353.354a.75.75 0 1 1-1.06-1.06l.353-.354a.75.75 0 0 1 1.06 0zM15 8a.75.75 0 0 1-.75.75h-.5a.75.75 0 0 1 0-1.5h.5A.75.75 0 0 1 15 8zM3 8a.75.75 0 0 1-.75.75h-.5a.75.75 0 0 1 0-1.5h.5A.75.75 0 0 1 3 8zm9.657 3.657a.75.75 0 0 1-1.06 0l-.354-.353a.75.75 0 1 1 1.06-1.06l.354.353a.75.75 0 0 1 0 1.06zm-9.9-9.9a.75.75 0 0 1-1.06 0l-.354-.353a.75.75 0 0 1 1.06-1.06l.354.353a.75.75 0 0 1 0 1.06z" />
              </svg>
            ) : (
              <svg viewBox="0 0 16 16" fill="currentColor" className="w-4 h-4">
                <path d="M6 .278a.768.768 0 0 1 .08.858 7.208 7.208 0 0 0-.878 3.46c0 4.021 3.278 7.277 7.318 7.277.527 0 1.04-.055 1.533-.16a.787.787 0 0 1 .81.316.733.733 0 0 1-.031.893A8.349 8.349 0 0 1 8.344 16C3.734 16 0 12.286 0 7.71 0 4.266 2.114 1.312 5.124.06A.752.752 0 0 1 6 .278z" />
              </svg>
            )}
          </button>

          <button
            onClick={onRefresh}
            className="text-xs px-3 py-1.5 rounded-md bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors text-gray-700 dark:text-slate-300 font-medium border border-gray-200 dark:border-slate-700"
          >
            ↻ <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>
    </header>
  )
}
