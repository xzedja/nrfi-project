export const SIGNAL_CONFIG = {
  nrfi_strong: {
    leftBar:    'border-l-emerald-500',
    bar:        'bg-emerald-500',
    badge:      'bg-emerald-500/[0.12] text-emerald-400 ring-1 ring-emerald-500/30',
    label:      'NRFI PICK',
    edgeColor:  'text-emerald-400',
    edgeBg:     'bg-emerald-500/[0.12] text-emerald-400 ring-1 ring-emerald-500/30',
    gaugeColor: 'bg-emerald-500',
    dotColor:   'text-emerald-500',
  },
  nrfi_lean: {
    leftBar:    'border-l-amber-500',
    bar:        'bg-amber-500',
    badge:      'bg-amber-500/[0.12] text-amber-400 ring-1 ring-amber-500/30',
    label:      'NRFI LEAN',
    edgeColor:  'text-amber-400',
    edgeBg:     'bg-amber-500/[0.12] text-amber-400 ring-1 ring-amber-500/30',
    gaugeColor: 'bg-amber-500',
    dotColor:   'text-amber-500',
  },
  yrfi_signal: {
    leftBar:    'border-l-sky-500',
    bar:        'bg-sky-500',
    badge:      'bg-sky-500/[0.12] text-sky-400 ring-1 ring-sky-500/30',
    label:      'YRFI SIGNAL',
    edgeColor:  'text-sky-400',
    edgeBg:     'bg-sky-500/[0.12] text-sky-400 ring-1 ring-sky-500/30',
    gaugeColor: 'bg-sky-500',
    dotColor:   'text-sky-500',
  },
  yrfi_slight: {
    leftBar:    'border-l-orange-500',
    bar:        'bg-orange-500',
    badge:      'bg-orange-500/[0.12] text-orange-400 ring-1 ring-orange-500/30',
    label:      'YRFI LEAN',
    edgeColor:  'text-orange-400',
    edgeBg:     'bg-orange-500/[0.12] text-orange-400 ring-1 ring-orange-500/30',
    gaugeColor: 'bg-orange-500',
    dotColor:   'text-orange-500',
  },
  yrfi_lean: {
    leftBar:    'border-l-red-500',
    bar:        'bg-red-500',
    badge:      'bg-red-500/[0.12] text-red-400 ring-1 ring-red-500/30',
    label:      'YRFI PICK',
    edgeColor:  'text-red-400',
    edgeBg:     'bg-red-500/[0.12] text-red-400 ring-1 ring-red-500/30',
    gaugeColor: 'bg-red-500',
    dotColor:   'text-red-500',
  },
  no_edge: {
    leftBar:    'border-l-violet-900',
    bar:        'bg-violet-800',
    badge:      'bg-violet-500/[0.08] text-violet-400/60 ring-1 ring-violet-500/20',
    label:      'NO EDGE',
    edgeColor:  'text-violet-400/60',
    edgeBg:     'bg-violet-500/[0.08] text-violet-400/60 ring-1 ring-violet-500/20',
    gaugeColor: 'bg-violet-700',
    dotColor:   'text-violet-600',
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
