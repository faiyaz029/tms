/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: { extend: { colors: { pitch: { 700: "#14703f", 900: "#0f3d26" } } } },
  plugins: [],
};
