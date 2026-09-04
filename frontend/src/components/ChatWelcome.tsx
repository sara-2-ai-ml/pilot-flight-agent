import { Plane } from "lucide-react";

const SUGGESTIONS = [
  {
    id: "tia-fra",
    label: "Find flights TIA to FRA",
    message: "Find flights TIA to FRA on 2025-09-15",
  },
  {
    id: "weekend-sep",
    label: "Cheapest weekend flights in September",
    message: "Find the cheapest weekend flights in September from Tirana to Europe",
  },
  {
    id: "book-now",
    label: "Book a flight now",
    message: "Book a flight now — help me choose route and date",
  },
] as const;

type ChatWelcomeProps = {
  onSuggestion: (message: string) => void;
  disabled?: boolean;
};

function PlaneIcon() {
  return <Plane className="chat-welcome__plane" size={52} strokeWidth={1.5} aria-hidden="true" />;
}

export function ChatWelcome({ onSuggestion, disabled = false }: ChatWelcomeProps) {
  return (
    <div className="chat-welcome chat-welcome--animated">
      <div className="chat-welcome__icon-wrap">
        <PlaneIcon />
      </div>
      <h2 className="chat-welcome__title">Where would you like to go?</h2>
      <p className="chat-welcome__subtitle">Pick a suggestion or type your own message below.</p>
      <div className="chat-suggestions" role="group" aria-label="Suggested prompts">
        {SUGGESTIONS.map((item, index) => (
          <button
            key={item.id}
            type="button"
            className="chat-suggestion-chip"
            style={{ animationDelay: `${120 + index * 80}ms` }}
            disabled={disabled}
            onClick={() => onSuggestion(item.message)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
