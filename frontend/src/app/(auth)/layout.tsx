import { montserrat } from "@/lib/fonts";
import { cn } from "@/lib/utils";

/** Unauthenticated routes (login): no app shell. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className={cn(montserrat.variable, "min-h-dvh bg-background font-brand [font-feature-settings:normal]")}>{children}</div>;
}
