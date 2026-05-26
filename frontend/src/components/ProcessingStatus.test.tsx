import "@testing-library/jest-dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProcessingStatus from "./ProcessingStatus";
import audioService from "../services/audioService";
import { useAuth } from "./auth/AuthContext";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({ transcriptionId: "42" }),
}));

vi.mock("./auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../services/audioService", () => ({
  default: {
    getTranscriptionStatus: vi.fn(),
    deleteTranscription: vi.fn(),
    retryTranscription: vi.fn(),
    getDemoTranscription: vi.fn(),
  },
}));

describe("ProcessingStatus Modal diagnostics", () => {
  beforeEach(() => {
    (useAuth as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      token: "test-token",
    });
    (audioService.getTranscriptionStatus as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValue({
        status: "queued",
        transcription_id: 42,
        selected_stem: "other",
        can_play_stem: false,
        can_generate_score: true,
      });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders readable Modal diagnostics when status fields are present", async () => {
    (audioService.getTranscriptionStatus as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValue({
        status: "queued",
        transcription_id: 42,
        selected_stem: "other",
        message: "Waiting for Modal capacity. Retry scheduled.",
        can_play_stem: false,
        can_generate_score: true,
        modal_status_detail: "rate_limited_retry",
        modal_dispatch_status: "retry_queued",
        modal_request_id: "mo-req-123",
        modal_retry_count: 2,
        modal_retry_at: "2026-05-26T07:30:00Z",
      });

    render(<ProcessingStatus />);

    expect(await screen.findByLabelText("Modal diagnostics")).toBeInTheDocument();
    expect(
      screen.getByText("Modal rate-limited; retry scheduled"),
    ).toBeInTheDocument();
    expect(screen.getByText("Modal retry queued")).toBeInTheDocument();
    expect(screen.getByText("mo-req-123")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/2026/i)).toBeInTheDocument();
  });

  it("keeps the diagnostic area hidden when Modal fields are absent", async () => {
    render(<ProcessingStatus />);

    await waitFor(() => {
      expect(audioService.getTranscriptionStatus).toHaveBeenCalledWith(
        42,
        "test-token",
      );
    });
    expect(screen.queryByLabelText("Modal diagnostics")).not.toBeInTheDocument();
  });
});
