import * as React from "react";

import { cn } from "@/lib/utils";

export const inputBaseClasses = [
  "flex w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-xs",
  "placeholder:text-subtle-foreground transition-[border-color,box-shadow] duration-150",
  "focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/20",
  "disabled:cursor-not-allowed disabled:opacity-60",
  "aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive/20",
].join(" ");

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  /** Visual size. */
  size?: "sm" | "md" | "lg";
  /** Icon/element rendered inside the field, on the left. */
  leftIcon?: React.ReactNode;
  /** Element rendered inside the field, on the right (e.g. a toggle button). */
  rightSlot?: React.ReactNode;
  /** Marks the field invalid (sets aria-invalid). */
  invalid?: boolean;
}

const sizeClasses = { sm: "h-8 text-[13px]", md: "h-9", lg: "h-10 text-[15px]" } as const;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, size = "md", leftIcon, rightSlot, invalid, type = "text", ...props }, ref) => {
    const input = (
      <input
        ref={ref}
        type={type}
        aria-invalid={invalid || props["aria-invalid"] || undefined}
        className={cn(
          inputBaseClasses,
          sizeClasses[size],
          "file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-medium",
          leftIcon && "pl-9",
          rightSlot && "pr-10",
          !leftIcon && !rightSlot && className,
        )}
        {...props}
      />
    );
    if (!leftIcon && !rightSlot) return input;
    return (
      <div className={cn("relative flex w-full items-center", className)}>
        {leftIcon ? (
          <span className="pointer-events-none absolute left-3 flex text-subtle-foreground [&_svg]:size-4">
            {leftIcon}
          </span>
        ) : null}
        {input}
        {rightSlot ? <span className="absolute right-1.5 flex items-center">{rightSlot}</span> : null}
      </div>
    );
  },
);
Input.displayName = "Input";
