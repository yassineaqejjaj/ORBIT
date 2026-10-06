"use client";

import * as React from "react";
import { ArrowUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export interface AskComposerProps {
  onSubmit: (question: string) => void;
  pending: boolean;
  autoFocus?: boolean;
}

export function AskComposer({ onSubmit, pending, autoFocus }: AskComposerProps) {
  const [value, setValue] = React.useState("");
  const submit = () => {
    const question = value.trim();
    if (!question || pending) return;
    onSubmit(question);
    setValue("");
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex items-end gap-2 rounded-composer border border-border bg-surface p-3 shadow-panel transition-[border-color,box-shadow] duration-150 focus-within:border-accent-coral/40 focus-within:ring-2 focus-within:ring-ring/25 sm:p-4"
    >
      <label htmlFor="ask-question" className="sr-only">
        Votre question
      </label>
      <Textarea
        id="ask-question"
        value={value}
        autoFocus={autoFocus}
        rows={2}
        maxLength={2000}
        placeholder="Que voulez-vous savoir sur le projet ? (Entrée pour envoyer, Maj+Entrée pour aller à la ligne)"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        className="min-h-[52px] resize-none border-0 bg-transparent px-1 text-[15px] leading-relaxed shadow-none focus-visible:border-0 focus-visible:ring-0"
      />
      <Button
        type="submit"
        size="icon"
        className="size-10 rounded-full"
        aria-label="Envoyer la question"
        loading={pending}
        disabled={!value.trim()}
      >
        <ArrowUp aria-hidden />
      </Button>
    </form>
  );
}
