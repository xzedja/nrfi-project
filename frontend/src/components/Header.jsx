function GridIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
      <rect x="1" y="1" width="6" height="6" rx="1" />
      <rect x="9" y="1" width="6" height="6" rx="1" />
      <rect x="1" y="9" width="6" height="6" rx="1" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </svg>
  )
}

function ListIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
      <rect x="1" y="2" width="14" height="2.5" rx="1" />
      <rect x="1" y="6.75" width="14" height="2.5" rx="1" />
      <rect x="1" y="11.5" width="14" height="2.5" rx="1" />
    </svg>
  )
}

export default function Header({ lastUpdated, onRefresh, theme, toggleTheme, viewMode, setViewMode }) {
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  })
  const timeStr = lastUpdated
    ? lastUpdated.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    : null

  return (
    <header className="sticky top-0 z-20 border-b border-violet-200 dark:border-violet-500/[0.15] bg-[#faf8ff]/90 dark:bg-[#090712]/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between gap-4">

        {/* Brand */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono font-bold text-lg tracking-tight text-violet-600 dark:text-violet-400">NRFI</span>
            <span className="font-mono text-xs text-violet-400/50 dark:text-violet-500/50 hidden sm:inline">/</span>
            <span className="font-mono text-xs text-violet-400/50 dark:text-violet-500/50 hidden sm:inline">YRFI</span>
          </div>
          <div className="hidden sm:flex items-center gap-1.5 pl-3 border-l border-violet-200 dark:border-violet-500/[0.15]">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs text-violet-400/70 dark:text-violet-400/50">{today}</span>
            {timeStr && (
              <span className="text-xs text-violet-400/40 dark:text-violet-500/40">· {timeStr}</span>
            )}
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2 shrink-0">

          {/* View toggle */}
          <div className="flex rounded-lg overflow-hidden border border-violet-200 dark:border-violet-500/[0.2] bg-violet-50 dark:bg-violet-500/[0.06]">
            {[
              { mode: 'tile',  Icon: GridIcon,  title: 'Card view' },
              { mode: 'table', Icon: ListIcon,  title: 'Table view' },
            ].map(({ mode, Icon, title }) => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                title={title}
                className={`p-2 transition-colors ${
                  viewMode === mode
                    ? 'bg-violet-200 dark:bg-violet-500/[0.2] text-violet-700 dark:text-violet-300'
                    : 'text-violet-400 dark:text-violet-500/60 hover:text-violet-600 dark:hover:text-violet-400'
                }`}
              >
                <Icon />
              </button>
            ))}
          </div>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            className="p-2 rounded-lg border border-violet-200 dark:border-violet-500/[0.2] bg-violet-50 dark:bg-violet-500/[0.06] text-violet-500 dark:text-violet-400/60 hover:text-violet-700 dark:hover:text-violet-300 transition-colors"
          >
            {theme === 'dark' ? (
              <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
                <path d="M8 12A4 4 0 1 0 8 4a4 4 0 0 0 0 8zm0 1.5a5.5 5.5 0 1 1 0-11 5.5 5.5 0 0 1 0 11zM8 1a.75.75 0 0 1 .75.75v.5a.75.75 0 0 1-1.5 0v-.5A.75.75 0 0 1 8 1zm0 12a.75.75 0 0 1 .75.75v.5a.75.75 0 0 1-1.5 0v-.5A.75.75 0 0 1 8 13zm5.657-9.657a.75.75 0 0 1 0 1.06l-.354.354a.75.75 0 1 1-1.06-1.06l.353-.354a.75.75 0 0 1 1.06 0zm-9.9 9.9a.75.75 0 0 1 0 1.06l-.353.354a.75.75 0 1 1-1.06-1.06l.353-.354a.75.75 0 0 1 1.06 0zM15 8a.75.75 0 0 1-.75.75h-.5a.75.75 0 0 1 0-1.5h.5A.75.75 0 0 1 15 8zM3 8a.75.75 0 0 1-.75.75h-.5a.75.75 0 0 1 0-1.5h.5A.75.75 0 0 1 3 8zm9.657 3.657a.75.75 0 0 1-1.06 0l-.354-.353a.75.75 0 1 1 1.06-1.06l.354.353a.75.75 0 0 1 0 1.06zm-9.9-9.9a.75.75 0 0 1-1.06 0l-.354-.353a.75.75 0 0 1 1.06-1.06l.354.353a.75.75 0 0 1 0 1.06z" />
              </svg>
            ) : (
              <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
                <path d="M6 .278a.768.768 0 0 1 .08.858 7.208 7.208 0 0 0-.878 3.46c0 4.021 3.278 7.277 7.318 7.277.527 0 1.04-.055 1.533-.16a.787.787 0 0 1 .81.316.733.733 0 0 1-.031.893A8.349 8.349 0 0 1 8.344 16C3.734 16 0 12.286 0 7.71 0 4.266 2.114 1.312 5.124.06A.752.752 0 0 1 6 .278z" />
              </svg>
            )}
          </button>

          {/* Refresh */}
          <button
            onClick={onRefresh}
            className="h-8 px-3 rounded-lg text-xs font-mono font-medium border border-violet-200 dark:border-violet-500/[0.2] bg-violet-50 dark:bg-violet-500/[0.06] text-violet-600 dark:text-violet-400/70 hover:text-violet-800 dark:hover:text-violet-300 hover:bg-violet-100 dark:hover:bg-violet-500/[0.12] transition-colors"
          >
            ↻<span className="hidden sm:inline ml-1.5">Refresh</span>
          </button>
        </div>
      </div>
    </header>
  )
}
