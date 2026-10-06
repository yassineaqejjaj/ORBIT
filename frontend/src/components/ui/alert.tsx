import * as React from "react";
import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";

import type { Tone } from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface AlertProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  tone?: Extract<Tone, "neutral" | "teal" | "green" | "amber" | "red" | "blue" | "violet">;
  title?: React.ReactNode;
  /** Custom icon; defaults per tone. Pass `null` to hide. */
  icon?: React.ReactNode | null;
  /** Right-aligned actions. */
  action?: React.ReactNode;
}

const DEFAULT_ICONS: Partial<Record<Tone, React.ReactNode>> = {
  amber: <TriangleAlert aria-hidden />,
  red: <CircleAlert aria-hidden />,
  green: <CircleCheck aria-hidden />,
  teal: <Info aria-hidden />,
  blue: <Info aria-hidden />,
  neutral: <Info aria-hidden />,
  violet: <Info aria-hidden />,
};

/** Inline callout (info / warning / error / success). */
export function Alert({ tone = "blue", title, icon, action, className, children, role, ...props }: AlertProps) {
  const t = toneClasses(tone);
  const resolvedIcon = icon === undefined ? DEFAULT_ICONS[tone] : icon;
  return (
    <div
      role={role ?? (tone === "red" || tone === "amber" ? "alert" : "status")}
      className={cn("flex items-start gap-3 rounded-lg border px-3.5 py-3 text-[13px]", t.callout, className)}
      {...props}
    >
      {resolvedIcon ? <span className={cn("mt-px flex shrink-0 [&_svg]:size-4", t.text)}>{resolvedIcon}</span> : null}
      <div className="grid min-w-0 flex-1 gap-0.5">
        {title ? <p className="font-semibold leading-snug">{title}</p> : null}
        {children ? <div className="leading-relaxed opacity-90">{children}</div> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}
