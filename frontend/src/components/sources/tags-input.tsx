"use client";

import * as React from "react";
import { Tag, X } from "lucide-react";

import { inputBaseClasses } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { normalizeTags } from "./acl";

export interface TagsInputProps {
  id?: string;
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  "aria-describedby"?: string;
}

/** Free-form tags: Enter / comma / Tab adds a tag, Backspace on empty input removes the last one. */
export function TagsInput({
  id,
  value,
  onChange,
  placeholder = "Ajouter une étiquette…",
  disabled,
  className,
  "aria-describedby": describedBy,
}: TagsInputProps) {
  const [draft, setDraft] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  const commit = (raw: string) => {
    const parts = raw.split(/[,;\n]/);
    const next = normalizeTags([...value, ...parts]);
    if (next.length !== value.length) onChange(next);
    setDraft("");
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if ((e.key === "Enter" || e.key === "," || e.key === ";" || (e.key === "Tab" && draft.trim())) && draft.trim()) {
      e.preventDefault();
      commit(draft);
    } else if (e.key === "Backspace" && !draft && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div
      className={cn(
        inputBaseClasses,
        "flex min-h-9 flex-wrap items-center gap-1.5 px-2 py-1.5 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20",
        disabled && "cursor-not-allowed opacity-60",
        className,
      )}
      onClick={() => inputRef.current?.focus()}
    >
      <Tag className="ml-1 size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
      {value.map((tag) => (
        <span
          key={tag}
          className="inline-flex h-6 items-center gap-1 rounded-md bg-muted pl-2 pr-1 text-xs font-medium text-foreground ring-1 ring-inset ring-border"
        >
          {tag}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onChange(value.filter((t) => t !== tag));
            }}
            disabled={disabled}
            className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Retirer l'étiquette ${tag}`}
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        id={id}
        value={draft}
        onChange={(e) => {
          const v = e.target.value;
          if (/[,;]/.test(v)) commit(v);
          else setDraft(v);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => draft.trim() && commit(draft)}
        onPaste={(e) => {
          const text = e.clipboardData.getData("text");
          if (/[,;\n]/.test(text)) {
            e.preventDefault();
            commit(`${draft}${text}`);
          }
        }}
        placeholder={value.length === 0 ? placeholder : ""}
        disabled={disabled}
        aria-describedby={describedBy}
        className="h-6 min-w-24 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle-foreground"
      />
    </div>
  );
}
