import { Montserrat } from "next/font/google";

import { cn } from "@/lib/utils";

/** Brand typeface for the sign-in pages only (NOVA: Montserrat 400–700). */
const montserrat = Montserrat({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-montserrat",
});

/** Unauthenticated routes (login): no app shell. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className={cn(montserrat.variable, "min-h-dvh bg-background font-brand [font-feature-settings:normal]")}>{children}</div>;
}
