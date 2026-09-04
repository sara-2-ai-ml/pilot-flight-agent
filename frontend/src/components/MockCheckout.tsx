import { ArrowLeft, CheckCircle2, CreditCard } from "lucide-react";
import { FormEvent, useState } from "react";
import type { PendingApproval } from "../types";

export type MockCardForm = {
  cardholderName: string;
  cardNumber: string;
  expiry: string;
  cvc: string;
};

type MockCheckoutProps = {
  pendingApproval: PendingApproval;
  selectedSeat: string | null;
  loading: boolean;
  error: string | null;
  onBack: () => void;
  onSubmit: (form: MockCardForm) => void;
};

export function MockCheckout({
  pendingApproval,
  selectedSeat,
  loading,
  error,
  onBack,
  onSubmit,
}: MockCheckoutProps) {
  const [form, setForm] = useState<MockCardForm>({
    cardholderName: pendingApproval.passenger,
    cardNumber: "",
    expiry: "",
    cvc: "",
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit(form);
  };

  const routeLabel = `${pendingApproval.route.origin} → ${pendingApproval.route.destination}`;

  return (
    <div className="checkout-overlay">
      <div className="checkout-panel glass-panel">
        <div className="checkout-header">
          <button type="button" className="icon-btn" onClick={onBack} aria-label="Back">
            <ArrowLeft size={18} />
          </button>
          <div>
            <p className="checkout-eyebrow">Mock payment</p>
            <h2>Complete your booking</h2>
          </div>
        </div>

        {error && <div className="banner banner--error">{error}</div>}

        <div className="checkout-layout">
          <aside className="checkout-summary">
            <p className="summary-label">Trip summary</p>
            <h3>{routeLabel}</h3>
            <dl className="summary-meta">
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
              {selectedSeat && (
                <div>
                  <dt>Seat</dt>
                  <dd>{selectedSeat}</dd>
                </div>
              )}
            </dl>
            <p className="checkout-note">Demo only — no real charge.</p>
          </aside>

          <form className="checkout-form" onSubmit={handleSubmit}>
            <div className="checkout-form-title">
              <CreditCard size={18} />
              <span>Card details</span>
            </div>

            <label className="checkout-field">
              <span>Name on card</span>
              <input
                type="text"
                value={form.cardholderName}
                onChange={(e) => setForm((prev) => ({ ...prev, cardholderName: e.target.value }))}
                placeholder="Jane Doe"
                autoComplete="cc-name"
                required
                disabled={loading}
              />
            </label>

            <label className="checkout-field">
              <span>Card number</span>
              <input
                type="text"
                inputMode="numeric"
                value={form.cardNumber}
                onChange={(e) => setForm((prev) => ({ ...prev, cardNumber: e.target.value }))}
                placeholder="4242 4242 4242 4242"
                autoComplete="cc-number"
                required
                disabled={loading}
              />
            </label>

            <div className="checkout-row">
              <label className="checkout-field">
                <span>Expiry</span>
                <input
                  type="text"
                  value={form.expiry}
                  onChange={(e) => setForm((prev) => ({ ...prev, expiry: e.target.value }))}
                  placeholder="MM/YY"
                  autoComplete="cc-exp"
                  required
                  disabled={loading}
                />
              </label>
              <label className="checkout-field">
                <span>CVC</span>
                <input
                  type="text"
                  inputMode="numeric"
                  value={form.cvc}
                  onChange={(e) => setForm((prev) => ({ ...prev, cvc: e.target.value }))}
                  placeholder="123"
                  autoComplete="cc-csc"
                  required
                  disabled={loading}
                />
              </label>
            </div>

            <button type="submit" className="pill-btn pill-btn--accent pill-btn--block" disabled={loading}>
              {loading ? "Processing…" : "Pay & confirm booking"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

type BookedConfirmationProps = {
  bookingId: string;
  message: string;
  onDone: () => void;
};

export function BookedConfirmation({ bookingId, message, onDone }: BookedConfirmationProps) {
  return (
    <div className="checkout-overlay">
      <div className="checkout-panel glass-panel booked-panel">
        <div className="booked-icon">
          <CheckCircle2 size={48} strokeWidth={1.5} />
        </div>
        <p className="checkout-eyebrow">All set</p>
        <h2>Booked!</h2>
        <p className="booked-message">{message}</p>
        {bookingId && <p className="booked-ref">Reference: {bookingId}</p>}
        <button type="button" className="pill-btn pill-btn--accent pill-btn--block" onClick={onDone}>
          Done
        </button>
      </div>
    </div>
  );
}
