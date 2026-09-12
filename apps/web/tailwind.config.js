/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: "#0E141B",
        surface: "#121B24",
        line: "#26323E",
        brass: { DEFAULT: "#C89A4C", soft: "#DDB66E" },
        steel: { DEFAULT: "#6E93AF", soft: "#8AAAC2" },
        ok: "#4E9E6E",
        warn: "#D3A03C",
        crit: "#D45A44",
      },
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Noto Sans Arabic",
          "Tahoma",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
