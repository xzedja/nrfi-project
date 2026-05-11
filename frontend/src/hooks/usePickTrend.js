import { useState, useEffect } from 'react'

export function usePickTrend() {
  const [trend, setTrend]   = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/dashboard/pick-trend')
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then(data => { setTrend(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  return { trend, loading }
}
