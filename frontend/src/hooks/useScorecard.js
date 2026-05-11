import { useState, useEffect } from 'react'
import { fetchScorecard } from '../api/dashboard'

export function useScorecard() {
  const [scorecard, setScorecard] = useState(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)

  useEffect(() => {
    fetchScorecard()
      .then(data => { setScorecard(data); setLoading(false) })
      .catch(e  => { setError(e.message); setLoading(false) })
  }, [])

  return { scorecard, loading, error }
}
