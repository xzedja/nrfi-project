const TABS = [
  { key: 'today',     label: 'Today' },
  { key: 'history',   label: 'History' },
  { key: 'simulator', label: 'Simulator' },
]

export default function NavTabs({ active, setActive }) {
  return (
    <div className="flex gap-0 border-b border-violet-200 dark:border-violet-500/[0.12] mb-6">
      {TABS.map(t => (
        <button
          key={t.key}
          onClick={() => setActive(t.key)}
          className={`px-5 py-2.5 text-sm font-semibold tracking-wide transition-all border-b-2 -mb-px ${
            active === t.key
              ? 'border-violet-500 text-violet-500 dark:text-violet-400'
              : 'border-transparent text-slate-500 dark:text-slate-600 hover:text-slate-700 dark:hover:text-slate-400'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
