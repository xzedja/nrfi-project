export default function Header({ lastUpdated, onRefresh }) {
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  })

  const timeStr = lastUpdated
    ? lastUpdated.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    : '—'

  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-black tracking-tight text-white">⚾ NRFI Dashboard</h1>
          <p className="text-xs text-slate-500 mt-0.5">{today}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-600 hidden sm:block">Updated {timeStr}</span>
          <button
            onClick={onRefresh}
            className="text-xs px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 transition-colors text-slate-300 font-medium"
          >
            ↻ Refresh
          </button>
        </div>
      </div>
    </header>
  )
}
