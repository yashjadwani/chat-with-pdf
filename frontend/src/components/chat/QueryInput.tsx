import { FormEvent, KeyboardEvent, useState } from "react";
import { SendHorizontal } from "lucide-react";
import { Button } from "../ui/Button";

export function QueryInput({
  disabled,
  onSend
}: {
  disabled?: boolean;
  onSend: (question: string) => void;
}) {
  const [question, setQuestion] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setQuestion("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  return (
    <form className="query-input" onSubmit={submit}>
      <textarea
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask about definitions, limitations, examples, or page-specific details..."
        disabled={disabled}
        rows={2}
      />
      <Button disabled={disabled || !question.trim()} type="submit" title="Send question" aria-label="Send question">
        <SendHorizontal size={18} />
      </Button>
    </form>
  );
}
