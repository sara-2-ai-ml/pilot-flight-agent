import { ArrowLeft } from "lucide-react";

const ROWS = [1, 2, 3, 4, 5, 6, 7, 8];
const LEFT = ["A", "B", "C"];
const RIGHT = ["D", "E", "F"];
const OCCUPIED = new Set(["2A", "2B", "3C", "4D", "5E", "6F", "7A", "8C"]);

type SeatPickerProps = {
  routeLabel: string;
  selectedSeat: string | null;
  loading: boolean;
  onSelect: (seat: string) => void;
  onBack: () => void;
  onContinue: () => void;
};

function seatClass(seatId: string, selectedSeat: string | null): string {
  if (OCCUPIED.has(seatId)) return "seat seat--occupied";
  if (selectedSeat === seatId) return "seat seat--selected";
  return "seat seat--available";
}

export function SeatPicker({
  routeLabel,
  selectedSeat,
  loading,
  onSelect,
  onBack,
  onContinue,
}: SeatPickerProps) {
  return (
    <div className="seat-overlay">
      <div className="seat-panel glass-panel">
        <div className="seat-header">
          <button type="button" className="icon-btn" onClick={onBack} aria-label="Back">
            <ArrowLeft size={18} />
          </button>
          <div>
            <p className="seat-eyebrow">Choose your seat</p>
            <h2>{routeLabel}</h2>
          </div>
        </div>

        <div className="seat-layout">
          <div className="seat-map-wrap">
            <div className="plane-nose" />
            <div className="seat-row-labels">
              <span />
              {LEFT.map((col) => (
                <span key={col}>{col}</span>
              ))}
              <span className="aisle-gap" />
              {RIGHT.map((col) => (
                <span key={col}>{col}</span>
              ))}
            </div>
            {ROWS.map((row) => (
              <div key={row} className="seat-row">
                <span className="row-num">{row}</span>
                {LEFT.map((col) => {
                  const id = `${row}${col}`;
                  const occupied = OCCUPIED.has(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      className={seatClass(id, selectedSeat)}
                      disabled={occupied || loading}
                      onClick={() => onSelect(id)}
                      aria-label={`Seat ${id}`}
                    />
                  );
                })}
                <span className="aisle-gap" />
                {RIGHT.map((col) => {
                  const id = `${row}${col}`;
                  const occupied = OCCUPIED.has(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      className={seatClass(id, selectedSeat)}
                      disabled={occupied || loading}
                      onClick={() => onSelect(id)}
                      aria-label={`Seat ${id}`}
                    />
                  );
                })}
              </div>
            ))}
            <div className="seat-legend">
              <span>
                <i className="dot dot--available" /> Available
              </span>
              <span>
                <i className="dot dot--selected" /> Selected
              </span>
              <span>
                <i className="dot dot--occupied" /> Occupied
              </span>
            </div>
          </div>

          <aside className="seat-summary">
            <p className="summary-label">Your selection</p>
            <h3>{selectedSeat ?? "—"}</h3>
            <dl className="summary-meta">
              <div>
                <dt>Class</dt>
                <dd>Economy</dd>
              </div>
              <div>
                <dt>Extra legroom</dt>
                <dd>{selectedSeat && selectedSeat.startsWith("1") ? "Included" : "Standard"}</dd>
              </div>
            </dl>
            <button
              type="button"
              className="pill-btn pill-btn--accent pill-btn--block"
              disabled={!selectedSeat || loading}
              onClick={onContinue}
            >
              {loading ? "Booking…" : "Continue to booking"}
            </button>
          </aside>
        </div>
      </div>
    </div>
  );
}
