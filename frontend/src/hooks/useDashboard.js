import { useState, useEffect, useCallback } from 'react'
import { fetchDashboard } from '../api/dashboard'

const REFRESH_MS = 5 * 60 * 1000

export function useDashboard() {
  const [games, setGames]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const data = await fetchDashboard()
      setGames(data)
      setLastUpdated(new Date())
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  return { games, loading, error, lastUpdated, refresh }
}
