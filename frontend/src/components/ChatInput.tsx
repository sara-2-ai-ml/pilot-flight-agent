import { Send } from "lucide-react";
import { FormEvent, forwardRef, useImperativeHandle, useState } from "react";

export type ChatInputHandle = {
  fillAndSend: (message: string) => void;
};

type ChatInputProps = {
  disabled?: boolean;
  placeholder?: string;
  onSend: (message: string) => void;
};

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { disabled = false, placeholder = "Message PILOT… e.g. Book the first flight", onSend },
  ref,
) {
  const [draft, setDraft] = useState("");

  useImperativeHandle(ref, () => ({
    fillAndSend(message: string) {
      const trimmed = message.trim();
      if (!trimmed || disabled) return;
      setDraft(trimmed);
      onSend(trimmed);
      setDraft("");
    },
  }));

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setDraft("");
  };

  return (
    <form className="chat-composer" onSubmit={handleSubmit}>
      <input
        type="text"
        className="chat-composer__input"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        aria-label="Message to agent"
        autoComplete="off"
      />
      <button type="submit" className="chat-send" disabled={disabled || !draft.trim()} aria-label="Send">
        <Send size={18} />
      </button>
    </form>
  );
});
