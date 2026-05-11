/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        mono: ['JetBrains Mono', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      keyframes: {
        shimmer: {
          '0%':   { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        scaleIn: {
          '0%':   { transform: 'scale(0.5)', opacity: '0' },
          '70%':  { transform: 'scale(1.1)' },
          '100%': { transform: 'scale(1)',   opacity: '1' },
        },
        fadeInUp: {
          '0%':   { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0) scale(1)' },
          '50%':      { transform: 'translateY(-28px) scale(1.04)' },
        },
        pulseGlow: {
          '0%, 100%': { opacity: '0.5' },
          '50%':      { opacity: '1' },
        },
      },
      animation: {
        'shimmer':      'shimmer 2.8s ease-in-out infinite',
        'scale-in':     'scaleIn 0.28s cubic-bezier(0.34, 1.56, 0.64, 1)',
        'fade-in-up':   'fadeInUp 0.32s ease-out',
        'float-slow':   'float 14s ease-in-out infinite',
        'float-med':    'float 10s ease-in-out infinite 2s',
        'float-fast':   'float 8s ease-in-out infinite 4s',
        'pulse-glow':   'pulseGlow 3s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
