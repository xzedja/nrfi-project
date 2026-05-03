export async function fetchDashboard() {
  const res = await fetch('/api/dashboard/today')
  if (!res.ok) throw new Error(`Server returned ${res.status}`)
  return res.json()
}
