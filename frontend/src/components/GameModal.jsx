import { useEffect } from 'react'
import GameCard from './GameCard'

export default function GameModal({ game, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      role="dialog"
      aria-modal="true"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative w-full sm:max-w-xl max-h-[92dvh] sm:max-h-[90vh] overflow-y-auto rounded-t-3xl sm:rounded-2xl bg-gray-50 dark:bg-[#0d1424] shadow-2xl">
        {/* Drag handle (mobile) */}
        <div className="flex justify-center pt-3 pb-1 sm:hidden">
          <div className="w-10 h-1 rounded-full bg-gray-300 dark:bg-slate-600" />
        </div>

        {/* Close button */}
        <div className="flex justify-end px-4 pt-3 pb-2 sm:pt-4">
          <button
            onClick={onClose}
            className="text-gray-400 dark:text-slate-500 hover:text-gray-700 dark:hover:text-slate-200 transition-colors p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800"
            aria-label="Close"
          >
            <svg viewBox="0 0 16 16" fill="currentColor" className="w-5 h-5">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z" />
            </svg>
          </button>
        </div>

        {/* GameCard rendered inside modal — no outer padding so card fills naturally */}
        <div className="px-4 pb-6">
          <GameCard game={game} />
        </div>
      </div>
    </div>
  )
}
