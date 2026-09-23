"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/** Ring geometry shared by the mark (unrotated ellipse centred on the planet). */
const RX = 13;
const RY = 2.8;
const TILT = -22;
const BACK_ARC = `M ${-RX} 0 A ${RX} ${RY} 0 0 1 ${RX} 0`;
const FRONT_ARC = `M ${-RX} 0 A ${RX} ${RY} 0 0 0 ${RX} 0`;
// Satellite on the front half of the ring (t = 50°), clear of the planet.
const SAT_X = +(RX * Math.cos((50 * Math.PI) / 180)).toFixed(2);
const SAT_Y = +(RY * Math.sin((50 * Math.PI) / 180)).toFixed(2);

export interface OrbitMarkProps extends React.SVGProps<SVGSVGElement> {
  /** "tile": white mark on a teal gradient tile (app icon). "bare": teal mark on transparent. */
  variant?: "tile" | "bare";
  /** Accessible title; omit when the mark sits next to the wordmark. */
  title?: string;
}

/**
 * ORBIT mark — a planet crossed by a tilted orbit ring carrying a satellite.
 * The ring passes behind the planet (occluded) and in front of it (knock-out gap).
 */
export function OrbitMark({ variant = "tile", title, className, ...props }: OrbitMarkProps) {
  const uid = React.useId().replace(/:/g, "");
  const gradId = `orbit-grad-${uid}`;
  const planetId = `orbit-planet-${uid}`;
  const maskId = `orbit-cut-${uid}`;
  const tile = variant === "tile";
  const ring = tile ? "#ffffff" : "var(--brand)";
  const planetFill = tile ? `url(#${planetId})` : `url(#${gradId})`;

  return (
    <svg
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      className={cn("shrink-0", className)}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <defs>
        <linearGradient id={gradId} x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2ED3B7" />
          <stop offset="0.55" stopColor="#0E9384" />
          <stop offset="1" stopColor="#125D56" />
        </linearGradient>
        <linearGradient id={planetId} x1="11" y1="10" x2="21" y2="22" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="1" stopColor="#CCFBEF" />
        </linearGradient>
        <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="32" height="32">
          <rect width="32" height="32" fill="#fff" />
          <g transform={`translate(16 16) rotate(${TILT})`}>
            <path d={FRONT_ARC} fill="none" stroke="#000" strokeWidth="3.8" strokeLinecap="round" />
          </g>
        </mask>
      </defs>

      {tile ? <rect width="32" height="32" rx="8" fill={`url(#${gradId})`} /> : null}

      <g transform={`translate(16 16) rotate(${TILT})`}>
        <path d={BACK_ARC} fill="none" stroke={ring} strokeOpacity={tile ? 0.6 : 0.45} strokeWidth="1.7" strokeLinecap="round" />
      </g>

      <circle cx="16" cy="16" r="6.1" fill={planetFill} mask={`url(#${maskId})`} />

      <g transform={`translate(16 16) rotate(${TILT})`}>
        <path d={FRONT_ARC} fill="none" stroke={ring} strokeWidth="1.7" strokeLinecap="round" />
        <circle cx={SAT_X} cy={SAT_Y} r="1.75" fill={tile ? "#ffffff" : "var(--brand)"} />
      </g>
    </svg>
  );
}

export interface OrbitLogoProps {
  className?: string;
  /** Mark size in px (default 28). */
  size?: number;
  /** Hide the tagline under the wordmark. */
  hideTagline?: boolean;
  tagline?: string;
}

/** Mark + "ORBIT" wordmark (+ optional tagline). */
export function OrbitLogo({ className, size = 28, hideTagline = false, tagline = "Contexte & mémoire" }: OrbitLogoProps) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <OrbitMark width={size} height={size} />
      <span className="grid leading-none">
        <span className="text-[15px] font-semibold tracking-[0.14em] text-foreground">ORBIT</span>
        {!hideTagline ? (
          <span className="mt-1 text-[10.5px] font-medium tracking-wide text-subtle-foreground">{tagline}</span>
        ) : null}
      </span>
      <span className="sr-only">ORBIT — plateforme de contexte et de mémoire pour agents IA</span>
    </span>
  );
}

/** The three NOVA programme constellation dots (NOVA Core red, ORBIT teal, FORGE violet). */
export function ConstellationDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)} aria-hidden>
      <span className="size-1.5 rounded-full bg-nova" />
      <span className="size-1.5 rounded-full bg-orbit" />
      <span className="size-1.5 rounded-full bg-forge" />
    </span>
  );
}
