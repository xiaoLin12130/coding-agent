/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#0f1115",
        panel: "#161a21",
        panelAlt: "#1c212a",
        edge: "#262d38",
        accent: "#4d7cfe",
      },
    },
  },
  plugins: [],
};
