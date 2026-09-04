export type BookingForm = {
  departure: string;
  arrival: string;
  departureDate: string;
  returnDate: string;
  passengers: string;
  email: string;
};

export type ApprovalRoute = {
  origin: string;
  destination: string;
  date: string;
  origin_city?: string | null;
  destination_city?: string | null;
};

export type ApprovalFlight = {
  id: string;
  carrier: string;
  origin: string;
  destination: string;
  departure_time: string;
  arrival_time: string;
};

export type PendingApproval = {
  action: string;
  step_id: string;
  worker: string;
  conversation_id: string;
  passenger: string;
  route: ApprovalRoute;
  flight: ApprovalFlight;
};

export type ChatResponse = {
  trace_id: string;
  conversation_id: string;
  message: string;
  pending_approval?: PendingApproval | null;
};

export type ApprovalResponse = {
  trace_id: string;
  conversation_id: string;
  message: string;
  success: boolean;
};

export type ChatMessage = {
  id: string;
  role: "user" | "agent" | "system";
  text: string;
};

export type AppStep = "landing" | "chat" | "seats" | "checkout" | "booked";

export type MockCheckoutResponse = {
  trace_id: string;
  conversation_id: string;
  message: string;
  success: boolean;
  booking_id: string;
};
