import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { AudioWaveform, LogOut } from "lucide-react";
import { Icon } from "./Icon";
import { useAuth } from "./auth/AuthContext";

export const PublicNav = () => (
  <header className="site-nav public-site-nav">
    <Link to="/" className="site-nav-brand" aria-label="MusicSheet Studio home">
      <span className="brand-mark">
        M
      </span>
      <span className="brand-copy">
        <span>AI Guitar</span>
        <span>Transcription Studio</span>
      </span>
    </Link>
    <nav className="site-nav-links" aria-label="Public navigation">
      <a href="/#features" className="site-nav-link">Features</a>
      <a href="/#how-it-works" className="site-nav-link">How it works</a>
      <a href="/#pricing" className="site-nav-link">Pricing</a>
      <a href="/#blog" className="site-nav-link">Blog</a>
      <a href="/#changelog" className="site-nav-link">Changelog</a>
    </nav>
    <Link to="/login" className="site-nav-link site-nav-signin">
      Sign in
    </Link>
    <Link to="/register" className="site-nav-cta">
      <span>Start your first score</span>
      <Icon name="arrow" />
    </Link>
  </header>
);

export const AppNav = () => {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isNewTranscriptionFlow =
    location.pathname.startsWith("/upload") ||
    location.pathname.startsWith("/processing");
  const isProjectViewer = location.pathname.startsWith("/transcription");

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <header className="site-nav app-site-nav">
      <Link to="/dashboard" className="site-nav-brand" aria-label="MusicSheet Studio dashboard">
        <span className="brand-mark">
          <AudioWaveform aria-hidden="true" />
        </span>
        <span>MusicSheet Studio</span>
      </Link>
      <nav className="site-nav-links" aria-label="Application navigation">
        <NavLink
          to="/dashboard"
          className={({ isActive }) =>
            `site-nav-link ${isActive || isProjectViewer ? "active" : ""}`
          }
        >
          Dashboard
        </NavLink>
        <NavLink
          to="/upload"
          className={({ isActive }) =>
            `site-nav-link ${isActive || isNewTranscriptionFlow ? "active" : ""}`
          }
        >
          New transcription
        </NavLink>
      </nav>
      <div className="site-nav-actions">
        <button type="button" onClick={handleLogout} className="logout-button icon-button" aria-label="Logout" title="Logout">
          <LogOut aria-hidden="true" />
        </button>
      </div>
    </header>
  );
};

export const PublicShell = ({ children }: { children: ReactNode }) => (
  <div className="site-shell public-shell">
    <PublicNav />
    {children}
  </div>
);

export const AppShell = ({ children }: { children: ReactNode }) => (
  <div className="site-shell app-shell">
    <AppNav />
    <main className="app-shell-main">{children}</main>
  </div>
);
