import { Link, NavLink, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { useAuth } from "./auth/AuthContext";
import { useTheme } from "./ThemeProvider";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `site-nav-link ${isActive ? "active" : ""}`;

export const PublicNav = () => (
  <header className="site-nav public-site-nav">
    <Link to="/" className="site-nav-brand" aria-label="MusicSheet Studio home">
      <span className="brand-mark">
        <Icon name="waveform" />
      </span>
      <span>MusicSheet Studio</span>
    </Link>
    <nav className="site-nav-links" aria-label="Public navigation">
      <NavLink to="/" className={navLinkClass} end>
        Home
      </NavLink>
      <NavLink to="/login" className={navLinkClass}>
        Sign in
      </NavLink>
      <NavLink to="/register" className={navLinkClass}>
        Create account
      </NavLink>
    </nav>
    <Link to="/register" className="site-nav-cta">
      <Icon name="arrow" />
      <span>Start a score</span>
    </Link>
  </header>
);

export const AppNav = () => {
  const { logout } = useAuth();
  const { isDarkMode, toggleDarkMode } = useTheme();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <header className="site-nav app-site-nav">
      <Link to="/dashboard" className="site-nav-brand" aria-label="MusicSheet Studio dashboard">
        <span className="brand-mark">
          <Icon name="waveform" />
        </span>
        <span>MusicSheet Studio</span>
      </Link>
      <nav className="site-nav-links" aria-label="Application navigation">
        <NavLink to="/dashboard" className={navLinkClass}>
          Dashboard
        </NavLink>
        <NavLink to="/upload" className={navLinkClass}>
          New transcription
        </NavLink>
      </nav>
      <div className="site-nav-actions">
        <button
          type="button"
          onClick={toggleDarkMode}
          className="theme-toggle-button icon-button"
          aria-label={isDarkMode ? "Switch to light mode" : "Switch to dark mode"}
          title={isDarkMode ? "Switch to light mode" : "Switch to dark mode"}
        >
          <Icon name={isDarkMode ? "sun" : "moon"} />
        </button>
        <button type="button" onClick={handleLogout} className="logout-button icon-button" aria-label="Logout" title="Logout">
          <Icon name="logout" />
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
