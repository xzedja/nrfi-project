const TABS = [
  { key: 'all',     label: 'All',         dot: '' },
  { key: 'nrfi',    label: 'NRFI Picks',  dot: '🟢' },
  { key: 'yrfi',    label: 'YRFI Signals',dot: '🔵' },
  { key: 'no_edge', label: 'No Edge',     dot: '⚪' },
]

export default function FilterTabs({ active, setActive, counts }) {
  return (
    <div className="flex gap-2 flex-wrap mb-6">
      {TABS.map(t => (
        <button
          key={t.key}
          onClick={() => setActive(t.key)}
          className={`
            px-4 py-2 rounded-full text-sm font-medium transition-all
            ${active === t.key
              ? 'bg-slate-700 text-white ring-1 ring-slate-500 shadow'
              : 'bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-300'}
          `}
        >
          {t.dot && <span className="mr-1.5">{t.dot}</span>}
          {t.label}
          <span className="ml-2 text-xs opacity-60">({counts[t.key] ?? 0})</span>
        </button>
      ))}
    </div>
  )
}
