"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return reduced;
}

interface OrbitDef {
  rx: number;
  ry: number;
  color: string;
  duration: number;
  begin: number;
  r: number;
  dashed?: boolean;
  opacity: number;
}

const ORBITS: OrbitDef[] = [
  { rx: 104, ry: 46, color: "#F8485E", duration: 16, begin: -3, r: 6, opacity: 0.55 },
  { rx: 158, ry: 70, color: "#CF208F", duration: 26, begin: -11, r: 4.5, dashed: true, opacity: 0.35 },
  { rx: 212, ry: 94, color: "#9B8AFB", duration: 38, begin: -24, r: 4.5, opacity: 0.25 },
];

const STARS: Array<[number, number, number]> = [
  [42, 48, 1.1], [96, 22, 0.8], [168, 60, 1.2], [300, 28, 0.9], [388, 52, 1.3], [470, 30, 0.8],
  [492, 118, 1], [30, 150, 0.9], [60, 290, 1.2], [126, 330, 0.8], [210, 318, 1], [338, 336, 1.1],
  [420, 306, 0.9], [486, 260, 1.2], [250, 12, 0.7], [446, 190, 0.8], [16, 222, 0.7], [362, 110, 0.6],
];

function ellipsePath(rx: number, ry: number): string {
  return `M ${-rx} 0 A ${rx} ${ry} 0 1 1 ${rx} 0 A ${rx} ${ry} 0 1 1 ${-rx} 0`;
}

/** Decorative animated constellation (login hero). Honors prefers-reduced-motion. */
export function OrbitHero({ className }: { className?: string }) {
  const reduced = usePrefersReducedMotion();
  const uid = React.useId().replace(/:/g, "");

  return (
    <svg viewBox="0 0 520 360" className={cn("h-auto w-full", className)} aria-hidden>
      <defs>
        <radialGradient id={`glow-${uid}`} cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#F8485E" stopOpacity="0.26" />
          <stop offset="1" stopColor="#F8485E" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`planet-${uid}`} cx="38%" cy="32%" r="75%">
          <stop offset="0" stopColor="#FD5051" />
          <stop offset="0.45" stopColor="#CF208F" />
          <stop offset="1" stopColor="#3A01D3" />
        </radialGradient>
        <filter id={`blur-${uid}`} x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
      </defs>

      {STARS.map(([x, y, r], i) => (
        <circle key={i} cx={x} cy={y} r={r} fill="#EFE9E7" opacity={0.25 + (i % 4) * 0.1} />
      ))}

      <circle cx="260" cy="180" r="150" fill={`url(#glow-${uid})`} />

      <g transform="translate(260 180) rotate(-16)">
        {ORBITS.map((o, i) => (
          <ellipse
            key={`ring-${i}`}
            rx={o.rx}
            ry={o.ry}
            fill="none"
            stroke={i === 0 ? "#F8485E" : "#D6CFCD"}
            strokeOpacity={o.opacity}
            strokeWidth={i === 0 ? 1.4 : 1}
            strokeDasharray={o.dashed ? "3 6" : undefined}
          />
        ))}
      </g>

      <circle cx="260" cy="180" r="36" fill={`url(#planet-${uid})`} />
      <ellipse cx="252" cy="168" rx="16" ry="9" fill="#FFFFFF" opacity="0.12" transform="rotate(-24 252 168)" />

      <g transform="translate(260 180) rotate(-16)">
        {ORBITS.map((o, i) => {
          const path = ellipsePath(o.rx, o.ry);
          // Static fallback position (reduced motion): distribute satellites around their rings.
          const angle = [0.35, 2.4, 4.1][i] ?? 0;
          const sx = o.rx * Math.cos(angle);
          const sy = o.ry * Math.sin(angle);
          return (
            <g key={`sat-${i}`}>
              <g transform={reduced ? `translate(${sx} ${sy})` : undefined}>
                <circle r={o.r * 2.2} fill={o.color} opacity="0.35" filter={`url(#blur-${uid})`} />
                <circle r={o.r} fill={o.color} />
                {!reduced ? (
                  <animateMotion dur={`${o.duration}s`} begin={`${o.begin}s`} repeatCount="indefinite" path={path} />
                ) : null}
              </g>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
