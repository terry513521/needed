export type ThemeMode = "day" | "dark";

export function DashboardHero({
  themeMode,
  onToggleTheme,
  subnetsCount,
  favoritesCount,
}: {
  themeMode: ThemeMode;
  onToggleTheme: () => void;
  subnetsCount: number | string;
  favoritesCount: number;
}) {
  return (
    <>
      <button
        type="button"
        className="mode-toggle"
        onClick={onToggleTheme}
        aria-label={themeMode === "day" ? "Switch to dark mode" : "Switch to day mode"}
        title={themeMode === "day" ? "Switch to dark mode" : "Switch to day mode"}
      >
        <span className="mode-toggle-icon" aria-hidden="true">
          {themeMode === "day" ? "Dark" : "Day"}
        </span>
        <span>{themeMode === "day" ? "Dark mode" : "Day mode"}</span>
      </button>
      <header className="dashboard-hero">
        <img
          className="hero-team-avatar"
          src="/favicon.png"
          alt="GRIT team avatar"
        />
        <div className="hero-copy">
          <span className="eyebrow">Bittensor intelligence hub</span>
          <h1 className="hero-title">
            <span>One team, Only Victory</span>
            <span className="hero-title-separator" aria-hidden="true">—</span>
            <span>Powered by</span>
            <span className="hero-grit-word">GRIT</span>
          </h1>
          <p className="hero-tagline">Victory Together</p>
          <div className="hero-message">
            <p>
              Success is never built by one person alone. It is created through shared effort,
              discipline, courage, and the belief that every teammate matters. As one team, we
              move with one purpose, one vision, and one determination to win together.
            </p>
            <p>
              Let us support one another, trust in our collective strengths, and remain committed to
              excellence. When we work together, obstacles become opportunities, and ambitions become
              achievements.
            </p>
            <p>
              Remember: our greatest strength is not in what we can accomplish individually, but in
              what we can achieve as one team.
            </p>
            <p>Together we strive. Together we succeed. Together we win.</p>
          </div>
        </div>
        <div className="hero-stats" aria-label="Dashboard summary">
          <div className="hero-stat">
            <span className="hero-stat-value">{subnetsCount}</span>
            <span className="hero-stat-label">Subnets</span>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-value">{favoritesCount}</span>
            <span className="hero-stat-label">Favorites</span>
          </div>
        </div>
      </header>
    </>
  );
}
