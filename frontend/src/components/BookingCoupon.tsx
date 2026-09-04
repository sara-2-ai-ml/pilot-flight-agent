import { Calendar, Mail, PlaneLanding, PlaneTakeoff, User } from "lucide-react";
import type { BookingForm } from "../types";

type BookingCouponProps = {
  form: BookingForm;
  loading: boolean;
  onChange: (field: keyof BookingForm, value: string) => void;
  onSubmit: () => void;
};

const FIELDS: Array<{
  key: keyof BookingForm;
  label: string;
  placeholder: string;
  icon: typeof PlaneTakeoff;
  type?: string;
}> = [
  { key: "departure", label: "Departure", placeholder: "Departure Airport", icon: PlaneTakeoff },
  { key: "arrival", label: "Arrival", placeholder: "Arrival Airport", icon: PlaneLanding },
  {
    key: "departureDate",
    label: "Departure Date",
    placeholder: "yyyy-mm-dd",
    icon: Calendar,
    type: "date",
  },
  {
    key: "returnDate",
    label: "Return date",
    placeholder: "yyyy-mm-dd",
    icon: Calendar,
    type: "date",
  },
  { key: "passengers", label: "Passengers", placeholder: "1", icon: User, type: "number" },
  { key: "email", label: "Email", placeholder: "Your Email", icon: Mail, type: "email" },
];

export function BookingCoupon({ form, loading, onChange, onSubmit }: BookingCouponProps) {
  return (
    <section className="booking-coupon" aria-label="Flight search">
      <form
        className="coupon-grid"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        {FIELDS.map(({ key, label, placeholder, icon: Icon, type = "text" }) => (
          <label key={key} className="coupon-field">
            <span className="coupon-label">
              <Icon size={14} strokeWidth={2} />
              {label}
            </span>
            <input
              type={type}
              min={type === "number" ? 1 : undefined}
              value={form[key]}
              onChange={(event) => onChange(key, event.target.value)}
              placeholder={placeholder}
              required={key === "departure" || key === "arrival" || key === "departureDate"}
              disabled={loading}
            />
          </label>
        ))}
        <button type="submit" className="coupon-submit" disabled={loading}>
          {loading ? "Searching…" : "Search Flights"}
        </button>
      </form>
    </section>
  );
}
