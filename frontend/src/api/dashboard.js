export async function fetchDashboard(dateStr = null) {
  const url = dateStr ? `/api/dashboard/today?date=${dateStr}` : '/api/dashboard/today'
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Server returned ${res.status}`)
  return res.json()
}

export async function fetchScorecard() {
  const res = await fetch('/api/dashboard/scorecard')
  if (!res.ok) throw new Error(`Server returned ${res.status}`)
  return res.json()
}
