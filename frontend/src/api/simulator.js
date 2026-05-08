export async function fetchSimulator(startYear = null) {
  const url = startYear ? `/api/dashboard/simulator?start_year=${startYear}` : '/api/dashboard/simulator'
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Server returned ${res.status}`)
  return res.json()
}
