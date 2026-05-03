import { useState, useEffect } from 'react'

export function useSeasonStats() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/dashboard/season-stats')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(data => { setStats(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  return { stats, loading, error }
}
