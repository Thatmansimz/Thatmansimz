/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        dark: {
          900: "#0a0e1a",
          800: "#0f1629",
          700: "#141c33",
          600: "#1a2440",
        },
        green: { neon: "#00ff88" },
        red: { neon: "#ff3366" },
      },
    },
  },
  plugins: [],
};
