import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "../Icon";
import { AuthStudioShell } from "./AuthStudioShell";
import { useAuth } from "./AuthContext";

const Login: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return;

    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setError(null);
    setIsLoading(true);

    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
      const response = await fetch(`${apiUrl}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams({
          username: email,
          password,
        }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Login failed");
      }

      const data = await response.json();
      login(data.access_token, { username: email, email });
      navigate("/dashboard");
    } catch (err: any) {
      if (err.name === "AbortError") return;
      setError(err.message || "An error occurred during login");
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
        setIsLoading(false);
      }
    }
  };

  return (
    <AuthStudioShell
      eyebrow="Guitar AI Studio"
      formTitle="Welcome back"
      formSubtitle="Sign in to continue to Guitar AI Studio."
      heroSubtitle="Convert recordings into polished guitar notation, tabs, and export-ready practice material."
    >
        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label htmlFor="email">Email address</label>
            <div className="auth-input-shell">
              <Icon name="mail" />
              <input
                type="email"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                disabled={isLoading}
                autoComplete="email"
                placeholder="you@example.com"
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <div className="password-input-wrapper auth-input-shell">
              <Icon name="lock" />
              <input
                type={showPassword ? "text" : "password"}
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
                autoComplete="current-password"
                placeholder="Enter your password"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="toggle-password icon-button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                title={showPassword ? "Hide password" : "Show password"}
              >
                <Icon name="eye" />
              </button>
            </div>
          </div>

          <div className="auth-form-options">
            <label className="auth-checkbox">
              <input type="checkbox" />
              <span>Remember me</span>
            </label>
            <button type="button" className="auth-text-button">
              Forgot password?
            </button>
          </div>

          <button type="submit" className="submit-button" disabled={isLoading}>
            <span>{isLoading ? "Signing in..." : "Sign in"}</span>
            <Icon name="arrow" />
          </button>

          {error && <div className="error-message">{error}</div>}

          <div className="auth-divider">
            <span>Or</span>
          </div>

          <button type="button" className="auth-social-button">
            <span className="auth-google-mark">G</span>
            Continue with Google
          </button>
          <button type="button" className="auth-social-button">
            <span className="auth-apple-mark">Apple</span>
            Continue with Apple
          </button>

          <div className="auth-footer">
            <p>
              No account yet? <Link to="/register">Create one</Link>
            </p>
          </div>
        </form>
    </AuthStudioShell>
  );
};

export default Login;
