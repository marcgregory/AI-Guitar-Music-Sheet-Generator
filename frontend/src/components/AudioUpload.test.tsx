import React from "react";
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
  default: {
    listTranscriptions: vi.fn(),
    uploadAudioFile: vi.fn(),
    extractAudioFromYouTube: vi.fn(),
  },
}));

vi.mock("gsap", () => ({
  default: {
    context: vi.fn((fn: Function) => ({ revert: vi.fn() })),
    from: vi.fn(),
    to: vi.fn(),
  },
}));

describe("AudioUpload", () => {
  const mockNavigate = vi.fn();

  beforeEach(() => {
    const mockedUseAuth = useAuth as unknown as { mockReturnValue: (value: unknown) => void };
    const mockedNavigate = useNavigate as unknown as { mockReturnValue: (value: unknown) => void };
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

    const fileInput = container.querySelector("input[type='file']") as HTMLInputElement;
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
});
