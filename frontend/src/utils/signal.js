export const SIGNAL_CONFIG = {
  nrfi_strong: {
    border:   'border-t-green-500',
    badge:    'bg-green-950 text-green-400 ring-1 ring-green-800',
    label:    'NRFI PICK',
    edgeColor:'text-green-400',
  },
  nrfi_lean: {
    border:   'border-t-yellow-500',
    badge:    'bg-yellow-950 text-yellow-400 ring-1 ring-yellow-800',
    label:    'NRFI LEAN',
    edgeColor:'text-yellow-400',
  },
  yrfi_signal: {
    border:   'border-t-blue-500',
    badge:    'bg-blue-950 text-blue-400 ring-1 ring-blue-800',
    label:    'YRFI SIGNAL',
    edgeColor:'text-blue-400',
  },
  yrfi_slight: {
    border:   'border-t-orange-500',
    badge:    'bg-orange-950 text-orange-400 ring-1 ring-orange-800',
    label:    'YRFI LEAN',
    edgeColor:'text-orange-400',
  },
  yrfi_lean: {
    border:   'border-t-red-500',
    badge:    'bg-red-950 text-red-400 ring-1 ring-red-800',
    label:    'YRFI PICK',
    edgeColor:'text-red-400',
  },
  no_edge: {
    border:   'border-t-slate-700',
    badge:    'bg-slate-800 text-slate-500 ring-1 ring-slate-700',
    label:    'NO EDGE',
    edgeColor:'text-slate-400',
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
