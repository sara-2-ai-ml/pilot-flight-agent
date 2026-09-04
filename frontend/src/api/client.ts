import type { ApprovalResponse, BookingForm, ChatResponse, MockCheckoutResponse } from "../types";

const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export function buildSearchMessage(form: BookingForm): string {
  const dep = form.departure.trim().toUpperCase();
  const arr = form.arrival.trim().toUpperCase();
  const date = form.departureDate.trim();
  const passengers = form.passengers.trim() || "1";
  const email = form.email.trim();

  let message = `Find flights from ${dep} to ${arr} on ${date} for ${passengers} passenger(s).`;
  if (form.returnDate.trim()) {
    message += ` Return on ${form.returnDate.trim()}.`;
  }
  if (email) {
    message += ` Contact email: ${email}.`;
  }
  return message;
}

export function buildBookMessage(seat: string, email: string): string {
  const contact = email.trim() ? ` Contact: ${email.trim()}.` : "";
  return `Book the first flight in seat ${seat}.${contact}`;
}

export function agentMessageHasFlightResults(message: string): boolean {
  return /Found \d+ (mock|live) flights from/i.test(message);
}

export function isBookNowIntent(message: string): boolean {
  const text = message.toLowerCase();
  return (
    /\b(book now|beje book|beje rezervimin|rezervo tani|pay now)\b/.test(text) ||
    (/\b(book|rezervo)\b/.test(text) && /\b(tani|now)\b/.test(text))
  );
}

export async function completeMockCheckout(
  conversationId: string,
  card: {
    cardholderName: string;
    cardNumber: string;
    expiry: string;
    cvc: string;
  },
): Promise<MockCheckoutResponse> {
  const response = await fetch(`${API_BASE}/checkout/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      cardholder_name: card.cardholderName,
      card_number: card.cardNumber,
      expiry: card.expiry,
      cvc: card.cvc,
    }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json() as Promise<MockCheckoutResponse>;
}

export async function postChat(
  message: string,
  conversationId?: string | null,
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId ?? undefined,
    }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json() as Promise<ChatResponse>;
}

export async function confirmApproval(conversationId: string): Promise<ApprovalResponse> {
  const response = await fetch(`${API_BASE}/approvals/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json() as Promise<ApprovalResponse>;
}

export async function cancelApproval(conversationId: string): Promise<ApprovalResponse> {
  const response = await fetch(`${API_BASE}/approvals/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json() as Promise<ApprovalResponse>;
}
