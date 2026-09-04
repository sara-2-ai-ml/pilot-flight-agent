import { useEffect, useRef } from "react";
import { ArrowLeft } from "lucide-react";
import type { ChatMessage, PendingApproval } from "../types";
import { ChatInput, type ChatInputHandle } from "./ChatInput";
import { ChatWelcome } from "./ChatWelcome";

type ChatPanelProps = {
  messages: ChatMessage[];
  loading: boolean;
  error: string | null;
  pendingApproval: PendingApproval | null;
  onClose: () => void;
  onSend: (message: string) => void;
  onChooseSeat: () => void;
  onConfirm: () => void;
  onCancelApproval: () => void;
  selectedSeat: string | null;
  showSeatAction: boolean;
};

export function ChatPanel({
  messages,
  loading,
  error,
  pendingApproval,
  onClose,
  onSend,
  onChooseSeat,
  onConfirm,
  onCancelApproval,
  selectedSeat,
  showSeatAction,
}: ChatPanelProps) {
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<ChatInputHandle>(null);

  const handleSuggestion = (message: string) => {
    inputRef.current?.fillAndSend(message);
  };

  useEffect(() => {
    const node = threadRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages, loading, pendingApproval]);

  return (
    <div className="chat-screen">
      <div className="chat-screen__backdrop" aria-hidden="true" />

      <div className="chat-screen__frame chat-screen__frame--enter">
        <header className="chat-screen__header">
          <button type="button" className="chat-back-btn" onClick={onClose} aria-label="Back">
            <ArrowLeft size={20} />
          </button>
          <div className="chat-screen__brand">
            <span className="chat-brand-mark">PILOT</span>
            <span className="chat-brand-sub">Flight concierge</span>
          </div>
          <div className="chat-header-spacer" />
        </header>

        <main className="chat-screen__main">
          {error && <div className="banner banner--error chat-banner">{error}</div>}

          <div className="chat-thread" ref={threadRef}>
            {messages.length === 0 && !loading && (
              <ChatWelcome onSuggestion={handleSuggestion} disabled={loading} />
            )}
            {messages.map((message) => (
              <div key={message.id} className={`bubble bubble--${message.role}`}>
                {message.text}
              </div>
            ))}
            {loading && <div className="bubble bubble--agent typing">Thinking…</div>}
          </div>
        </main>

        <footer className="chat-screen__footer">
          {pendingApproval && (
            <div className="approval-card approval-card--large">
              <div className="approval-card__head">
                <p className="approval-title">Ready to book</p>
                <p className="approval-route">
                  {pendingApproval.route.origin_city ?? pendingApproval.route.origin} (
                  {pendingApproval.route.origin}) →{" "}
                  {pendingApproval.route.destination_city ?? pendingApproval.route.destination} (
                  {pendingApproval.route.destination})
                </p>
              </div>
              <dl className="approval-details">
                <div>
                  <dt>Date</dt>
                  <dd>{pendingApproval.route.date}</dd>
                </div>
                <div>
                  <dt>Flight</dt>
                  <dd>{pendingApproval.flight.id}</dd>
                </div>
                <div>
                  <dt>Departure</dt>
                  <dd>{pendingApproval.flight.departure_time}</dd>
                </div>
                <div>
                  <dt>Passenger</dt>
                  <dd>{pendingApproval.passenger}</dd>
                </div>
                {selectedSeat && (
                  <div>
                    <dt>Seat</dt>
                    <dd>{selectedSeat}</dd>
                  </div>
                )}
              </dl>
              <div className="approval-actions approval-actions--large">
                <button type="button" className="pill-btn pill-btn--accent" onClick={onConfirm}>
                  Pay & book
                </button>
                <button type="button" className="pill-btn pill-btn--ghost" onClick={onChooseSeat}>
                  Choose seat
                </button>
                <button type="button" className="pill-btn pill-btn--ghost" onClick={onCancelApproval}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {showSeatAction && !pendingApproval && !loading && (
            <div className="chat-actions">
              <button type="button" className="pill-btn pill-btn--accent" onClick={onChooseSeat}>
                Choose seat
              </button>
            </div>
          )}

          <ChatInput ref={inputRef} disabled={loading} onSend={onSend} />
        </footer>
      </div>
    </div>
  );
}
