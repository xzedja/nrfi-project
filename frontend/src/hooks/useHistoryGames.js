import { useState, useCallback } from 'react'
import { fetchDashboard } from '../api/dashboard'

export function useHistoryGames() {
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async (dateStr) => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchDashboard(dateStr)
      setGames(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  return { games, loading, error, load }
}
