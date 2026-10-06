"use client";

import * as React from "react";
import Image from "next/image";

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

/** Intrinsic size of public/brand/orbit-wordmark*.png (cropped from the brand artwork). */
const WORDMARK_WIDTH = 319;
const WORDMARK_HEIGHT = 120;

export interface OrbitWordmarkProps {
  /** Rendered height in px (width follows the artwork ratio). */
  height?: number;
  /**
   * "auto": light artwork, lifted variant in dark mode. "on-dark": always the lifted variant (dark surfaces such as
   * the login hero). "on-light": always the original artwork.
   */
  tone?: "auto" | "on-dark" | "on-light";
  className?: string;
  /** Accessible name; pass "" when a visible text already names ORBIT. */
  alt?: string;
}

/** The "orbit" wordmark (red → violet → indigo gradient). */
export function OrbitWordmark({ height = 24, tone = "auto", className, alt = "ORBIT" }: OrbitWordmarkProps) {
  const width = Math.round((height * WORDMARK_WIDTH) / WORDMARK_HEIGHT);
  const size = { width, height, style: { width, height }, draggable: false, priority: true, unoptimized: true } as const;
  if (tone !== "auto") {
    const src = tone === "on-dark" ? "/brand/orbit-wordmark-dark.png" : "/brand/orbit-wordmark.png";
    return <Image src={src} alt={alt} {...size} className={cn("select-none", className)} />;
  }
  return (
    <span className={cn("inline-flex", className)}>
      <Image src="/brand/orbit-wordmark.png" alt={alt} {...size} className="select-none dark:hidden" />
      <Image src="/brand/orbit-wordmark-dark.png" alt="" aria-hidden {...size} className="hidden select-none dark:block" />
    </span>
  );
}

export interface OrbitLogoProps {
  className?: string;
  /** Wordmark height in px (default 26). */
  size?: number;
  /** Hide the tagline under the wordmark. */
  hideTagline?: boolean;
  tagline?: string;
}

/** "orbit" wordmark (+ optional tagline). */
export function OrbitLogo({ className, size = 26, hideTagline = false, tagline = "Contexte & mémoire" }: OrbitLogoProps) {
  return (
    <span className={cn("inline-grid justify-items-start gap-1 leading-none", className)}>
      <OrbitWordmark height={size} alt="ORBIT — plateforme de contexte et de mémoire pour agents IA" />
      {!hideTagline ? (
        <span className="text-[10.5px] font-medium tracking-wide text-subtle-foreground">{tagline}</span>
      ) : null}
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
