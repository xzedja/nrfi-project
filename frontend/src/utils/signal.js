export const SIGNAL_CONFIG = {
  nrfi_strong: {
    border:    'border-t-green-500',
    bar:       'bg-green-500',
    badge:     'bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-400 ring-1 ring-green-200 dark:ring-green-800',
    label:     'NRFI PICK',
    edgeColor: 'text-green-600 dark:text-green-400',
  },
  nrfi_lean: {
    border:    'border-t-yellow-500',
    bar:       'bg-yellow-500',
    badge:     'bg-yellow-50 dark:bg-yellow-950 text-yellow-700 dark:text-yellow-400 ring-1 ring-yellow-200 dark:ring-yellow-800',
    label:     'NRFI LEAN',
    edgeColor: 'text-yellow-600 dark:text-yellow-400',
  },
  yrfi_signal: {
    border:    'border-t-blue-500',
    bar:       'bg-blue-500',
    badge:     'bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-400 ring-1 ring-blue-200 dark:ring-blue-800',
    label:     'YRFI SIGNAL',
    edgeColor: 'text-blue-600 dark:text-blue-400',
  },
  yrfi_slight: {
    border:    'border-t-orange-500',
    bar:       'bg-orange-500',
    badge:     'bg-orange-50 dark:bg-orange-950 text-orange-700 dark:text-orange-400 ring-1 ring-orange-200 dark:ring-orange-800',
    label:     'YRFI LEAN',
    edgeColor: 'text-orange-600 dark:text-orange-400',
  },
  yrfi_lean: {
    border:    'border-t-red-500',
    bar:       'bg-red-500',
    badge:     'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-400 ring-1 ring-red-200 dark:ring-red-800',
    label:     'YRFI PICK',
    edgeColor: 'text-red-600 dark:text-red-400',
  },
  no_edge: {
    border:    'border-t-gray-300 dark:border-t-slate-700',
    bar:       'bg-gray-300 dark:bg-slate-600',
    badge:     'bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-500 ring-1 ring-gray-300 dark:ring-slate-700',
    label:     'NO EDGE',
    edgeColor: 'text-gray-400 dark:text-slate-400',
  },
}

export function getSignal(signal) {
  return SIGNAL_CONFIG[signal] || SIGNAL_CONFIG.no_edge
}

export function pct(val, digits = 1) {
  if (val == null) return '—'
  return (val * 100).toFixed(digits) + '%'
}

export function fmtEdge(val) {
  if (val == null) return '—'
  const pp = (val * 100).toFixed(1)
  return val >= 0 ? '+' + pp + '%' : pp + '%'
}

export function fmtOdds(val) {
  if (val == null) return '—'
  return val > 0 ? '+' + val : String(val)
}

export function fmtEra(val) {
  if (val == null) return '—'
  return val.toFixed(2)
}

export function fmtVelo(val, trend) {
  if (val == null) return '—'
  const arrow = trend == null ? '' : trend > 0.5 ? ' ↑' : trend < -0.5 ? ' ↓' : ''
  return val.toFixed(1) + ' mph' + arrow
}

export function fmtRest(val) {
  if (val == null) return '—'
  const d = Math.round(val)
  return d + (d === 1 ? ' day' : ' days')
}
