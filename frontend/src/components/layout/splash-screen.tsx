import { OrbitMark } from "@/components/brand/orbit-logo";

/** Full-screen loading state (auth check, redirects). */
export function SplashScreen({ label = "Chargement d'ORBIT…" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background" role="status" aria-live="polite">
      <div className="relative">
        <span className="absolute inset-0 animate-ping rounded-xl bg-brand/20" aria-hidden />
        <OrbitMark width={44} height={44} className="relative" />
      </div>
      <p className="text-[13px] text-muted-foreground">{label}</p>
    </div>
  );
}
