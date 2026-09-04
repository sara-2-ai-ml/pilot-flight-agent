import { useCallback, useMemo, useState } from "react";
import {
  buildSearchMessage,
  cancelApproval,
  completeMockCheckout,
  isBookNowIntent,
  postChat,
} from "./api/client";
import { BookingCoupon } from "./components/BookingCoupon";
import { ChatPanel } from "./components/ChatPanel";
import { Header } from "./components/Header";
import { Hero } from "./components/Hero";
import { BookedConfirmation, MockCheckout, type MockCardForm } from "./components/MockCheckout";
import { SeatPicker } from "./components/SeatPicker";
import type { AppStep, BookingForm, ChatMessage, PendingApproval } from "./types";
import "./App.css";

const EMPTY_FORM: BookingForm = {
  departure: "TIA",
  arrival: "FRA",
  departureDate: "2025-09-15",
  returnDate: "",
  passengers: "1",
  email: "",
};

function nextId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function App() {
  const [form, setForm] = useState<BookingForm>(EMPTY_FORM);
  const [step, setStep] = useState<AppStep>("landing");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [selectedSeat, setSelectedSeat] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [bookingId, setBookingId] = useState<string | null>(null);
  const [bookedMessage, setBookedMessage] = useState<string | null>(null);

  const routeLabel = useMemo(() => {
    const dep = form.departure.trim().toUpperCase() || "—";
    const arr = form.arrival.trim().toUpperCase() || "—";
    return `${dep} → ${arr}`;
  }, [form.arrival, form.departure]);

  const showChat = chatOpen && step === "chat";

  const pushMessage = useCallback((role: ChatMessage["role"], text: string) => {
    setMessages((prev) => [...prev, { id: nextId(), role, text }]);
  }, []);

  const openCheckout = useCallback(() => {
    if (!pendingApproval) return;
    setStep("checkout");
    setChatOpen(false);
    setError(null);
  }, [pendingApproval]);

  const sendUserMessage = useCallback(
    async (userText: string) => {
      const trimmed = userText.trim();
      if (!trimmed || loading) return;

      setLoading(true);
      setError(null);
      pushMessage("user", trimmed);
      setStep("chat");
      setChatOpen(true);

      if (pendingApproval && isBookNowIntent(trimmed)) {
        pushMessage("agent", "Perfect — enter your card details on the payment screen.");
        setLoading(false);
        openCheckout();
        return;
      }

      try {
        const response = await postChat(trimmed, conversationId);
        setConversationId(response.conversation_id);
        pushMessage("agent", response.message);
        if (response.pending_approval) {
          setPendingApproval(response.pending_approval);
        } else {
          setPendingApproval(null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Request failed");
      } finally {
        setLoading(false);
      }
    },
    [conversationId, loading, openCheckout, pendingApproval, pushMessage],
  );

  const handleSearch = async () => {
    setPendingApproval(null);
    setSelectedSeat(null);
    setBookingId(null);
    setBookedMessage(null);
    await sendUserMessage(buildSearchMessage(form));
  };

  const handleBookWithSeat = () => {
    if (!selectedSeat) return;
    setStep("chat");
    setChatOpen(true);
  };

  const handleCheckoutSubmit = async (card: MockCardForm) => {
    if (!conversationId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await completeMockCheckout(conversationId, card);
      setBookingId(response.booking_id);
      setBookedMessage(response.message);
      setPendingApproval(null);
      setStep("booked");
      pushMessage("agent", response.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
    } finally {
      setLoading(false);
    }
  };

  const handleCancelApproval = async () => {
    if (!conversationId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await cancelApproval(conversationId);
      pushMessage("agent", response.message);
      setPendingApproval(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    } finally {
      setLoading(false);
    }
  };

  const openChat = () => {
    setStep("chat");
    setChatOpen(true);
  };

  const handleBookedDone = () => {
    setStep("chat");
    setChatOpen(true);
    setBookingId(null);
    setBookedMessage(null);
  };

  return (
    <div className={`app-shell ${showChat ? "app-shell--chat" : ""}`}>
      <img src="/istockphoto-1526986072-2048x2048.jpg" alt="" className="hero-bg" aria-hidden="true" />
      <div className={`hero-scrim ${showChat ? "hero-scrim--chat" : ""}`} />

      {!showChat && (
        <>
          <Header />
          <Hero onOpenChat={openChat} />

          <BookingCoupon
            form={form}
            loading={loading && step !== "seats" && step !== "checkout"}
            onChange={(field, value) => setForm((prev) => ({ ...prev, [field]: value }))}
            onSubmit={handleSearch}
          />
        </>
      )}

      {showChat && (
        <ChatPanel
          messages={messages}
          loading={loading}
          error={error}
          pendingApproval={pendingApproval}
          onClose={() => {
            setChatOpen(false);
            setStep("landing");
          }}
          onSend={sendUserMessage}
          onChooseSeat={() => setStep("seats")}
          onConfirm={openCheckout}
          onCancelApproval={handleCancelApproval}
          selectedSeat={selectedSeat}
          showSeatAction={!!pendingApproval}
        />
      )}

      {step === "seats" && (
        <SeatPicker
          routeLabel={routeLabel}
          selectedSeat={selectedSeat}
          loading={loading}
          onSelect={setSelectedSeat}
          onBack={() => {
            setStep("chat");
            setChatOpen(true);
          }}
          onContinue={handleBookWithSeat}
        />
      )}

      {step === "checkout" && pendingApproval && (
        <MockCheckout
          pendingApproval={pendingApproval}
          selectedSeat={selectedSeat}
          loading={loading}
          error={error}
          onBack={() => {
            setStep("chat");
            setChatOpen(true);
            setError(null);
          }}
          onSubmit={handleCheckoutSubmit}
        />
      )}

      {step === "booked" && bookedMessage && (
        <BookedConfirmation
          bookingId={bookingId ?? ""}
          message={bookedMessage}
          onDone={handleBookedDone}
        />
      )}
    </div>
  );
}
