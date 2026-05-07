const TABS = [
  { key: 'all',     label: 'All Games',     dot: null,              activeClass: 'bg-slate-700/80 text-white ring-1 ring-white/10' },
  { key: 'nrfi',    label: 'NRFI',          dot: 'bg-emerald-500',  activeClass: 'bg-emerald-500/[0.15] text-emerald-400 ring-1 ring-emerald-500/30' },
  { key: 'yrfi',    label: 'YRFI',          dot: 'bg-sky-500',      activeClass: 'bg-sky-500/[0.15] text-sky-400 ring-1 ring-sky-500/30' },
  { key: 'no_edge', label: 'No Edge',       dot: 'bg-slate-600',    activeClass: 'bg-slate-700/60 text-slate-400 ring-1 ring-slate-600/50' },
]

export default function FilterTabs({ active, setActive, counts }) {
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
                : 'bg-white/[0.04] dark:bg-white/[0.03] text-slate-500 hover:text-slate-300 hover:bg-white/[0.07] ring-1 ring-white/[0.06] dark:ring-white/[0.05]'}
            `}
          >
            {t.dot && (
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isActive ? t.dot : 'bg-slate-600'}`} />
            )}
            <span>{t.label}</span>
            <span className={`font-mono text-xs ${isActive ? 'opacity-70' : 'opacity-40'}`}>
              {counts[t.key] ?? 0}
            </span>
          </button>
        )
      })}
    </div>
  )
}
