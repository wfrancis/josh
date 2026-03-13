/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        si: {
          navy: '#05224B',
          blue: '#134791',
          bright: '#116DFF',
          medium: '#4980C1',
          orange: '#FF5F00',
          cream: '#F3EFE5',
          'cream-light': '#FDFBF7',
          'cream-warm': '#FFF8ED',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
