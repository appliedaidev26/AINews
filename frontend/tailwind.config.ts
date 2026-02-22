import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        accent: {
          DEFAULT: '#2563eb', // blue-600
          light:   '#eff6ff', // blue-50
          dark:    '#1d4ed8', // blue-700
        },
      },
    },
  },
  plugins: [],
}

export default config
