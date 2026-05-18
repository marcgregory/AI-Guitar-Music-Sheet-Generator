import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "../Icon";
import { AuthStudioShell } from "./AuthStudioShell";
import { useAuth } from "./AuthContext";

const Register: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [confirmPassword, setConfirmPassword] = useState("");
  const abortControllerRef = useRef<AbortController | null>(null);

  const errorMessage = (detail: unknown, fallback: string) => {
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "error" in detail) {
      return String((detail as { error?: unknown }).error || fallback);
    }
    return fallback;
  };

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return;

    setError(null);
    setIsLoading(true);

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      setIsLoading(false);
      return;
    }

    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
      const response = await fetch(`${apiUrl}/auth/register`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email,
          username,
          password,
        }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorMessage(errorData.detail, "Registration failed"));
      }

      await response.json();

      const loginResponse = await fetch(`${apiUrl}/auth/login`, {
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

      if (!loginResponse.ok) {
        const errorData = await loginResponse.json();
        throw new Error(errorMessage(errorData.detail, "Registration succeeded, but sign-in failed"));
      }

      const tokenData = await loginResponse.json();
      login(tokenData.access_token, { username, email }, tokenData.refresh_token);
      navigate("/dashboard");
    } catch (err: any) {
      if (err.name === "AbortError") return;
      setError(err.message || "An error occurred during registration");
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
      formTitle="Create account"
      formSubtitle="Build your private guitar transcription library."
      heroSubtitle="Build a private library of AI-assisted transcriptions for practice, teaching, and arrangement."
    >
        <form onSubmit={handleSubmit} className="auth-form auth-form-register">
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <div className="auth-input-shell">
              <Icon name="user" />
              <input
                type="text"
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
                maxLength={50}
                autoFocus
                disabled={isLoading}
                autoComplete="username"
                placeholder="Enter your username"
              />
            </div>
          </div>

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
                minLength={8}
                disabled={isLoading}
                autoComplete="new-password"
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

          <div className="form-group">
            <label htmlFor="confirmPassword">Confirm password</label>
            <div className="password-input-wrapper auth-input-shell">
              <Icon name="lock" />
              <input
                type={showConfirmPassword ? "text" : "password"}
                id="confirmPassword"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={8}
                disabled={isLoading}
                autoComplete="new-password"
                placeholder="Confirm your password"
              />
              <button
                type="button"
                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                className="toggle-password icon-button"
                aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                title={showConfirmPassword ? "Hide password" : "Show password"}
              >
                <Icon name="eye" />
              </button>
            </div>
          </div>

          <div className="auth-form-options">
            <label className="auth-checkbox">
              <input type="checkbox" required />
              <span>Agree to private studio terms</span>
            </label>
          </div>

          <button type="submit" className="submit-button" disabled={isLoading}>
            <span>{isLoading ? "Creating account..." : "Create account"}</span>
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
              Already registered? <Link to="/login">Sign in</Link>
            </p>
          </div>
        </form>
    </AuthStudioShell>
  );
};

export default Register;
