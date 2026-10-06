import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Providers } from "@/components/providers/providers";
import { themeInitScript } from "@/lib/theme-script";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "ORBIT — Contexte & mémoire pour agents IA",
    template: "%s · ORBIT",
  },
  description:
    "ORBIT fournit à chaque agent IA le bon contexte, au bon moment : pertinence, fraîcheur, provenance et droits d'accès, avec une explicabilité complète.",
  applicationName: "ORBIT",
  authors: [{ name: "Devoteam — Programme NOVA" }],
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf8f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0c0d" },
  ],
  colorScheme: "light dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-dvh bg-background font-sans text-foreground antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
