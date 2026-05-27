import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import AudioUpload from "./AudioUpload";
import audioService from "../services/audioService";
import { useAuth } from "./auth/AuthContext";
import { useNavigate } from "react-router-dom";

vi.mock("react-router-dom", () => ({
  useNavigate: vi.fn(),
}));

vi.mock("./auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../services/audioService", () => ({
  DAILY_LIMIT_QUEUE_EMPTY_MESSAGE:
    "The queue can be empty, but your daily processing quota is already used.",
  isDailyProcessingLimitError: (error: unknown) => {
    const err = error as {
      response?: { status?: number; data?: { detail?: unknown } };
    };
    return (
      err.response?.status === 429 &&
      typeof err.response.data?.detail === "string" &&
      err.response.data.detail.includes("Daily processing limit reached")
    );
  },
  default: {
    listTranscriptions: vi.fn(),
    uploadAudioFile: vi.fn(),
    extractAudioFromYouTube: vi.fn(),
  },
}));

vi.mock("gsap", () => ({
  default: {
    context: vi.fn(() => ({ revert: vi.fn() })),
    from: vi.fn(),
    to: vi.fn(),
  },
}));

describe("AudioUpload", () => {
  const mockNavigate = vi.fn();

  beforeEach(() => {
    const mockedUseAuth = useAuth as unknown as {
      mockReturnValue: (value: unknown) => void;
    };
    const mockedNavigate = useNavigate as unknown as {
      mockReturnValue: (value: unknown) => void;
    };
    const mockedAudioService = audioService as unknown as {
      listTranscriptions: { mockResolvedValue: (value: unknown) => void };
      uploadAudioFile: { mockRejectedValue: (value: unknown) => void };
    };

    mockedUseAuth.mockReturnValue({ token: "dummy-token" });
    mockedNavigate.mockReturnValue(mockNavigate);
    mockedAudioService.listTranscriptions.mockResolvedValue([]);
    mockedAudioService.uploadAudioFile.mockRejectedValue({
      response: { status: 409, data: { detail: "Conflict" } },
    });

    window.matchMedia = vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    }));
  });

  it("shows the friendly 409 error text when another transcription is processing", async () => {
    const { container } = render(<AudioUpload />);

    await waitFor(() => {
      expect(audioService.listTranscriptions).toHaveBeenCalled();
    });

    fireEvent.click(screen.getAllByRole("radio")[3]);

    const fileInput = container.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["RIFF...."], "sample.wav", { type: "audio/wav" })],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /Upload audio/i }));

    await waitFor(() => {
      expect(
        screen.getByText(
          /Another user is currently processing a transcription\. Please try again in a few minutes\./i,
        ),
      ).toBeInTheDocument();
    });
  });

  it("shows specific copy for daily processing limit errors", async () => {
    const mockedAudioService = audioService as unknown as {
      uploadAudioFile: { mockRejectedValue: (value: unknown) => void };
    };
    mockedAudioService.uploadAudioFile.mockRejectedValue({
      response: {
        status: 429,
        data: {
          detail: "Daily processing limit reached. Please try again tomorrow.",
        },
      },
    });
    const { container } = render(<AudioUpload />);

    await waitFor(() => {
      expect(audioService.listTranscriptions).toHaveBeenCalled();
    });

    fireEvent.click(screen.getAllByRole("radio")[3]);
    const fileInput = container.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["RIFF...."], "sample.wav", { type: "audio/wav" })],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /Upload audio/i }));

    expect(
      await screen.findByText(
        "The queue can be empty, but your daily processing quota is already used.",
      ),
    ).toBeInTheDocument();
  });
});
