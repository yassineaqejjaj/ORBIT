import localFont from "next/font/local";

// Self-hosted variable font (latin subset, SIL OFL 1.1): the build never depends on fonts.googleapis.com.

/** Brand typeface for the sign-in pages (same file as NOVA). */
export const montserrat = localFont({
  src: "../assets/fonts/montserrat-latin-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-montserrat",
  display: "swap",
});
