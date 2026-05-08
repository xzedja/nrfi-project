const TABS = [
  { key: 'all',     label: 'All Games', dot: null,             activeClass: 'bg-violet-500/[0.15] text-violet-400 dark:text-violet-300 ring-1 ring-violet-500/30' },
  { key: 'nrfi',   label: 'NRFI',      dot: 'bg-emerald-500', activeClass: 'bg-emerald-500/[0.12] text-emerald-400 ring-1 ring-emerald-500/25' },
  { key: 'yrfi',   label: 'YRFI',      dot: 'bg-sky-500',     activeClass: 'bg-sky-500/[0.12] text-sky-400 ring-1 ring-sky-500/25' },
  { key: 'no_edge',label: 'No Edge',   dot: 'bg-violet-700',  activeClass: 'bg-violet-500/[0.08] text-violet-400/60 ring-1 ring-violet-500/20' },
]

export default function FilterTabs({ active, setActive, counts, sortBy, setSortBy }) {
  return (
    <div className="flex items-center gap-2 flex-wrap mb-5">
      {TABS.map(t => {
        const isActive = active === t.key
        return (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            className={`
              flex items-center gap-2 h-8 px-3.5 rounded-lg text-sm font-medium transition-all
              ${isActive
                ? t.activeClass
                : 'bg-violet-500/[0.05] text-violet-500/60 dark:text-violet-400/40 hover:text-violet-600 dark:hover:text-violet-300 hover:bg-violet-500/[0.10] ring-1 ring-violet-500/[0.10]'}
            `}
          >
            {t.dot && (
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isActive ? t.dot : 'bg-violet-500/30'}`} />
            )}
            <span>{t.label}</span>
            <span className={`font-mono text-xs ${isActive ? 'opacity-70' : 'opacity-40'}`}>
              {counts[t.key] ?? 0}
            </span>
          </button>
        )
      })}

      {/* Sort toggle */}
      <div className="ml-auto flex items-center gap-1 rounded-lg ring-1 ring-violet-500/[0.12] bg-violet-500/[0.04] p-0.5">
        {['signal', 'time'].map(opt => (
          <button
            key={opt}
            onClick={() => setSortBy(opt)}
            className={`h-7 px-3 rounded-md text-xs font-semibold tracking-wide transition-all capitalize ${
              sortBy === opt
                ? 'bg-violet-500/[0.18] text-violet-300 dark:text-violet-300'
                : 'text-violet-500/50 dark:text-violet-400/35 hover:text-violet-400/70'
            }`}
          >
            {opt === 'signal' ? 'Signal' : 'Time'}
          </button>
        ))}
      </div>
    </div>
  )
}
