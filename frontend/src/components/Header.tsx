export function Header() {
  return (
    <header className="site-header">
      <div className="brand-mark" aria-label="PILOT">
        <span className="brand-emoji" aria-hidden="true">
          ✈️
        </span>
      </div>
      <nav className="site-nav" aria-label="Main">
        <a href="#about">About</a>
        <a href="#solutions">Solutions</a>
        <a href="#contact">Contact</a>
      </nav>
      <button type="button" className="pill-btn pill-btn--light pill-btn--sm">
        Group Flight
        <span className="pill-icon pill-icon--dark">+</span>
      </button>
    </header>
  );
}
