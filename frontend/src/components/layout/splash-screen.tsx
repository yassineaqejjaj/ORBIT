import { OrbitWordmark } from "@/components/brand/orbit-logo";

/** Full-screen loading state (auth check, redirects). */
export function SplashScreen({ label = "Chargement d'ORBIT…" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background" role="status" aria-live="polite">
      <OrbitWordmark height={36} className="animate-pulse motion-reduce:animate-none" />
      <p className="text-[13px] text-muted-foreground">{label}</p>
    </div>
  );
}
