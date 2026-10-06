import * as React from "react";

import { toneClasses, type AnyTone } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Historical palette tone or NOVA tone (neutral · accent · success · warning · danger). */
  tone?: AnyTone;
  variant?: "soft" | "outline" | "solid";
  size?: "sm" | "md";
  /** Leading colored dot. */
  dot?: boolean;
  /** Pulsing dot (e.g. "running"). */
  pulse?: boolean;
  /** Leading icon (lucide element). */
  icon?: React.ReactNode;
  /** Monospace text (codes, ids). */
  mono?: boolean;
}

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  (
    { className, tone = "neutral", variant = "soft", size = "sm", dot, pulse, icon, mono, children, ...props },
    ref,
  ) => {
    const t = toneClasses(tone);
    return (
      <span
        ref={ref}
        className={cn(
          "inline-flex max-w-full shrink-0 items-center gap-1 whitespace-nowrap rounded-sm font-medium ring-1 ring-inset",
          size === "sm" ? "h-5 px-1.5 text-[11px] leading-none" : "h-6 px-2 text-[12px]",
          variant === "soft" && t.soft,
          variant === "outline" && t.outline,
          variant === "solid" && t.solid,
          mono && "font-mono tracking-tight",
          "[&_svg]:size-3 [&_svg]:shrink-0",
          className,
        )}
        {...props}
      >
        {dot || pulse ? (
          <span className="relative flex size-1.5 shrink-0" aria-hidden>
            {pulse ? <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", t.dot)} /> : null}
            <span className={cn("relative inline-flex size-1.5 rounded-full", t.dot)} />
          </span>
        ) : null}
        {icon}
        <span className="truncate">{children}</span>
      </span>
    );
  },
);
Badge.displayName = "Badge";
