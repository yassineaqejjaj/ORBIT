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
      className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-xs focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/15"
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
        placeholder="Posez une question sur le projet… (Entrée pour envoyer, Maj+Entrée pour aller à la ligne)"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        className="min-h-[44px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
      />
      <Button type="submit" size="icon-sm" aria-label="Envoyer la question" loading={pending} disabled={!value.trim()}>
        <ArrowUp aria-hidden />
      </Button>
    </form>
  );
}
