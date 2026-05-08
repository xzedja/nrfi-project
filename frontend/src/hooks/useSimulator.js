import { useState, useEffect } from 'react'
import { fetchSimulator } from '../api/simulator'

export function useSimulator(startYear) {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchSimulator(startYear)
      .then(data => { setEntries(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [startYear])

  return { entries, loading, error }
}
