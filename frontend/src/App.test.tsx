import "@testing-library/jest-dom";

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./components/MotionDirector", () => ({
  default: () => null,
}));

vi.mock("./components/SiteNav", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PublicShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("./components/LandingPage", () => ({
  default: () => <div>Landing page</div>,
}));

vi.mock("./components/auth/Login", () => ({
  default: () => <div>Login page</div>,
}));

vi.mock("./components/auth/Register", () => ({
  default: () => <div>Register page</div>,
}));

vi.mock("./components/auth/Dashboard", () => ({
  default: () => <div>Dashboard page</div>,
}));

vi.mock("./components/AudioUpload", () => ({
  default: () => <div>Upload page</div>,
}));

vi.mock("./components/ProcessingStatus", () => ({
  default: () => <div>Processing page</div>,
}));

vi.mock("./components/TranscriptionViewer", () => ({
  default: () => <div>Transcription page</div>,
}));

vi.mock("./components/admin/AdminJobsDashboard", () => ({
  default: () => <div>Admin jobs page</div>,
}));

const createToken = (exp: number) => {
  const payload = window.btoa(JSON.stringify({ sub: "tester", exp }));
  return `header.${payload}.signature`;
};

const storeValidAuth = () => {
  localStorage.setItem("access_token", createToken(Math.floor(Date.now() / 1000) + 3600));
  localStorage.setItem("user", JSON.stringify({ username: "tester", email: "tester@example.com" }));
};

describe("App routing", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("keeps authenticated users out of the login page", async () => {
    storeValidAuth();
    window.history.replaceState({}, "", "/login");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Dashboard page")).toBeInTheDocument());
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("keeps authenticated users out of the register page", async () => {
    storeValidAuth();
    window.history.replaceState({}, "", "/register");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Dashboard page")).toBeInTheDocument());
    expect(screen.queryByText("Register page")).not.toBeInTheDocument();
  });

  it("sends authenticated users from the public home to the dashboard", async () => {
    storeValidAuth();

    render(<App />);

    await waitFor(() => expect(screen.getByText("Dashboard page")).toBeInTheDocument());
    expect(screen.queryByText("Landing page")).not.toBeInTheDocument();
  });

  it("keeps the public home accessible when users are logged out", async () => {
    render(<App />);

    await waitFor(() => expect(screen.getByText("Landing page")).toBeInTheDocument());
    expect(screen.queryByText("Dashboard page")).not.toBeInTheDocument();
  });

  it("keeps the login page accessible when users are logged out", async () => {
    window.history.replaceState({}, "", "/login");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Login page")).toBeInTheDocument());
    expect(screen.queryByText("Dashboard page")).not.toBeInTheDocument();
  });

  it("keeps admin jobs protected for unauthenticated users", async () => {
    window.history.replaceState({}, "", "/admin/jobs");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Login page")).toBeInTheDocument());
    expect(screen.queryByText("Admin jobs page")).not.toBeInTheDocument();
  });

  it("allows authenticated users through to admin jobs", async () => {
    storeValidAuth();
    window.history.replaceState({}, "", "/admin/jobs");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Admin jobs page")).toBeInTheDocument());
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("sends authenticated users from unknown paths back to the dashboard", async () => {
    storeValidAuth();
    window.history.replaceState({}, "", "/made-up-path");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Dashboard page")).toBeInTheDocument());
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("sends unauthenticated users from unknown paths to login", async () => {
    window.history.replaceState({}, "", "/made-up-path");

    render(<App />);

    await waitFor(() => expect(screen.getByText("Login page")).toBeInTheDocument());
  });
});
