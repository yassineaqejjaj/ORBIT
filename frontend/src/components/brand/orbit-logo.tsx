"use client";

import * as React from "react";
import Image from "next/image";

import { cn } from "@/lib/utils";

/** ORBIT "o" ring path (same geometry as src/app/icon.svg and public/orbit-mark.svg). */
const RING_PATH =
  "M16 2.42a14 13.58 0 1 0 0 27.16a14 13.58 0 1 0 0-27.16Z M16.02 10.15a5.91 5.91 0 1 1 0 11.82a5.91 5.91 0 1 1 0-11.82Z";

export interface OrbitMarkProps extends React.SVGProps<SVGSVGElement> {
  /** Accessible title; omit when the mark sits next to a visible name. */
  title?: string;
}

/**
 * ORBIT mark — the "o" ring of the wordmark, in the brand gradient (coral → magenta → indigo).
 * The gradient is reserved to the brand (logo, icon, presence ring).
 */
export function OrbitMark({ title, className, ...props }: OrbitMarkProps) {
  const gradId = `orbit-ring-${React.useId().replace(/:/g, "")}`;
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
        <linearGradient id={gradId} x1="2" y1="0" x2="30" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FD5051" />
          <stop offset="0.4" stopColor="#FB3268" />
          <stop offset="0.6" stopColor="#CF208F" />
          <stop offset="0.85" stopColor="#7407C0" />
          <stop offset="1" stopColor="#3A01D3" />
        </linearGradient>
      </defs>
      <path fill={`url(#${gradId})`} fillRule="evenodd" d={RING_PATH} />
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

/** The three NOVA programme constellation dots (NOVA Core coral, ORBIT magenta, FORGE violet). */
export function ConstellationDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)} aria-hidden>
      <span className="size-1.5 rounded-full bg-nova" />
      <span className="size-1.5 rounded-full bg-orbit" />
      <span className="size-1.5 rounded-full bg-forge" />
    </span>
  );
}
