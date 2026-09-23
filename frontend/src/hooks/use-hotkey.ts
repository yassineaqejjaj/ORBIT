"use client";

import * as React from "react";

export interface HotkeyOptions {
  /** Require Cmd (macOS) or Ctrl (others). */
  mod?: boolean;
  shift?: boolean;
  /** Fire even when focus is in an input/textarea/contenteditable. */
  allowInInputs?: boolean;
  enabled?: boolean;
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/** Global keyboard shortcut, e.g. useHotkey("k", open, { mod: true }). */
export function useHotkey(key: string, handler: (e: KeyboardEvent) => void, options: HotkeyOptions = {}) {
  const { mod = false, shift = false, allowInInputs = mod, enabled = true } = options;
  const ref = React.useRef(handler);
  React.useEffect(() => {
    ref.current = handler;
  }, [handler]);

  React.useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== key.toLowerCase()) return;
      if (mod !== (e.metaKey || e.ctrlKey)) return;
      if (shift !== e.shiftKey) return;
      if (!allowInInputs && isTypingTarget(e.target)) return;
      e.preventDefault();
      ref.current(e);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [key, mod, shift, allowInInputs, enabled]);
}
