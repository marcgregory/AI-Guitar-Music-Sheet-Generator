import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { AudioWaveform, LogOut, Menu, X } from "lucide-react";
import { Icon } from "./Icon";
import { useAuth } from "./auth/AuthContext";

export const PublicNav = () => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const closeMobileMenu = () => setIsMobileMenuOpen(false);

  return (
    <header className="site-nav public-site-nav">
      <Link
        to="/"
        className="site-nav-brand"
        aria-label="MusicSheet Studio home"
        onClick={closeMobileMenu}
      >
        <span className="brand-mark">M</span>
        <span className="brand-copy">
          <span>AI Guitar</span>
          <span>Transcription Studio</span>
        </span>
      </Link>
      <button
        type="button"
        className="site-nav-menu-toggle"
        aria-label={isMobileMenuOpen ? "Close navigation" : "Open navigation"}
        aria-controls="public-site-nav-menu"
        aria-expanded={isMobileMenuOpen}
        onClick={() => setIsMobileMenuOpen((open) => !open)}
      >
        {isMobileMenuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
      </button>
      <div
        id="public-site-nav-menu"
        className={`site-nav-menu ${isMobileMenuOpen ? "is-open" : ""}`}
      >
        <nav className="site-nav-links" aria-label="Public navigation">
          <a href="/#features" className="site-nav-link" onClick={closeMobileMenu}>
            Features
          </a>
          <a
            href="/#how-it-works"
            className="site-nav-link"
            onClick={closeMobileMenu}
          >
            How it works
          </a>
          <a href="/#pricing" className="site-nav-link" onClick={closeMobileMenu}>
            Pricing
          </a>
          <a href="/#blog" className="site-nav-link" onClick={closeMobileMenu}>
            Blog
          </a>
          <a
            href="/#changelog"
            className="site-nav-link"
            onClick={closeMobileMenu}
          >
            Changelog
          </a>
        </nav>
        <div className="site-nav-actions">
          <Link
            to="/login"
            className="site-nav-link site-nav-signin"
            onClick={closeMobileMenu}
          >
            Sign in
          </Link>
          <Link to="/register" className="site-nav-cta" onClick={closeMobileMenu}>
            <span>Start your first score</span>
            <Icon name="arrow" />
          </Link>
        </div>
      </div>
    </header>
  );
};

export const AppNav = () => {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const isNewTranscriptionFlow =
    location.pathname.startsWith("/upload") ||
    location.pathname.startsWith("/processing");
  const isProjectViewer = location.pathname.startsWith("/transcription");

  const closeMobileMenu = () => setIsMobileMenuOpen(false);

  const handleLogout = () => {
    closeMobileMenu();
    logout();
    navigate("/login");
  };

  return (
    <header className="site-nav app-site-nav">
      <Link
        to="/dashboard"
        className="site-nav-brand"
        aria-label="MusicSheet Studio dashboard"
        onClick={closeMobileMenu}
      >
        <span className="brand-mark">
          <AudioWaveform aria-hidden="true" />
        </span>
        <span>MusicSheet Studio</span>
      </Link>
      <button
        type="button"
        className="site-nav-menu-toggle"
        aria-label={isMobileMenuOpen ? "Close navigation" : "Open navigation"}
        aria-controls="app-site-nav-menu"
        aria-expanded={isMobileMenuOpen}
        onClick={() => setIsMobileMenuOpen((open) => !open)}
      >
        {isMobileMenuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
      </button>
      <div
        id="app-site-nav-menu"
        className={`site-nav-menu ${isMobileMenuOpen ? "is-open" : ""}`}
      >
        <nav className="site-nav-links" aria-label="Application navigation">
          <NavLink
            to="/dashboard"
            onClick={closeMobileMenu}
            className={({ isActive }) =>
              `site-nav-link ${isActive || isProjectViewer ? "active" : ""}`
            }
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/upload"
            onClick={closeMobileMenu}
            className={({ isActive }) =>
              `site-nav-link ${isActive || isNewTranscriptionFlow ? "active" : ""}`
            }
          >
            New transcription
          </NavLink>
          <NavLink
            to="/admin/jobs"
            onClick={closeMobileMenu}
            className={({ isActive }) =>
              `site-nav-link ${isActive ? "active" : ""}`
            }
          >
            Jobs
          </NavLink>
        </nav>
        <div className="site-nav-actions">
          <button
            type="button"
            onClick={handleLogout}
            className="logout-button icon-button"
            aria-label="Logout"
            title="Logout"
          >
            <LogOut aria-hidden="true" />
          </button>
        </div>
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
