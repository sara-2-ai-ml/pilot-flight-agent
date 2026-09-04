type HeroProps = {
  onOpenChat: () => void;
};

export function Hero({ onOpenChat }: HeroProps) {
  return (
    <section className="hero">
      <div className="hero-grid">
        <div className="hero-left">
          <h1 className="hero-title">PILOT</h1>
          <p className="hero-copy">
            Experience seamless luxury travel designed for modern explorers, blending
            elegance, comfort, and effortless journey.
          </p>
          <div className="hero-actions">
            <button type="button" className="pill-btn pill-btn--accent" onClick={onOpenChat}>
              Ask PILOT
              <span className="pill-icon pill-icon--light">✈</span>
            </button>
            <button type="button" className="pill-btn pill-btn--light">
              Group Flight
              <span className="pill-icon pill-icon--dark">+</span>
            </button>
          </div>
        </div>
        <div className="hero-right">
          <p className="hero-tagline">
            <span className="accent-text">Luxury,</span> Now Boarding
          </p>
        </div>
      </div>
    </section>
  );
}
