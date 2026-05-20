import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TranscriptionViewer from "./TranscriptionViewer";
import audioService, { type Transcription } from "../services/audioService";
import { useAuth } from "./auth/AuthContext";

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ transcriptionId: "42" }),
}));

vi.mock("./auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../services/audioService", () => ({
  default: {
    getTranscriptionResult: vi.fn(),
    listInstrumentTracks: vi.fn(),
    generateTab: vi.fn(),
    generateLyrics: vi.fn(),
    resolvePlayableAudioUrl: vi.fn((value: string | null | undefined) =>
      value || null,
    ),
    getAudioFileUrl: vi.fn((value: string | null | undefined) => value || null),
  },
}));

const stemReadyTranscription: Transcription = {
  id: 42,
  title: "Stem Ready Song",
  selected_stem: "other",
  processing_status: "stem_ready",
  separated_audio_url: "/demo/stem.wav",
  can_play_stem: true,
  can_generate_score: false,
  user_id: 1,
  is_processed: true,
  created_at: "2026-05-20T00:00:00Z",
};

describe("TranscriptionViewer generate tabs polling", () => {
  beforeEach(() => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    Object.defineProperty(window.HTMLMediaElement.prototype, "load", {
      configurable: true,
      value: vi.fn(),
    });

    (useAuth as unknown as { mockReturnValue: (value: unknown) => void })
      .mockReturnValue({ token: "test-token" });

    const mockedAudioService = audioService as unknown as {
      getTranscriptionResult: ReturnType<typeof vi.fn>;
      listInstrumentTracks: ReturnType<typeof vi.fn>;
      generateTab: ReturnType<typeof vi.fn>;
      generateLyrics: ReturnType<typeof vi.fn>;
    };

    mockedAudioService.getTranscriptionResult.mockResolvedValue({
      ...stemReadyTranscription,
    });
    mockedAudioService.listInstrumentTracks.mockResolvedValue([]);
    mockedAudioService.generateTab.mockResolvedValue({
      status: "processing",
      transcription_id: 42,
      message: "Tab generation started.",
    });
    mockedAudioService.generateLyrics.mockResolvedValue({
      status: "stem_ready",
      lyrics_generation_status: "processing",
      transcription_id: 42,
      message: "Lyrics generation started.",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps generating UI when polling returns stale stem_ready", async () => {
    render(<TranscriptionViewer />);

    const generateButton = await screen.findByRole("button", {
      name: /Generate Tabs/i,
    });

    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(audioService.generateTab).toHaveBeenCalledWith(42, "test-token");
      expect(screen.getAllByText(/Generating tabs\.\.\./i).length).toBeGreaterThan(0);
    });

    expect(
      screen.getByRole("button", { name: /Generating tabs/i }),
    ).toBeDisabled();

    await waitFor(() => {
      expect(audioService.getTranscriptionResult).toHaveBeenCalledTimes(2);
      expect(screen.getAllByText(/Generating tabs\.\.\./i).length).toBeGreaterThan(0);
    }, { timeout: 3500 });

    expect(
      screen.queryByText(
        "Stem is ready. Listen first, then generate tabs if the stem sounds useful.",
      ),
    ).not.toBeInTheDocument();
  }, 10000);

  it("renders readable drum tabs as wrapped measure notation", async () => {
    const drumNotes = JSON.stringify({
      drum_hits: [
        { onset: 0, offset: 0.08, intensity: 0.9, instrument: "kick" },
        { onset: 0.25, offset: 0.33, intensity: 0.4, instrument: "hi-hat" },
        { onset: 0.5, offset: 0.58, intensity: 0.75, instrument: "snare" },
        { onset: 0.75, offset: 0.83, intensity: 0.4, instrument: "hi-hat" },
      ],
      rhythm_analysis: { total_duration: 1, grid_size: 0.125 },
    });

    (audioService.getTranscriptionResult as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValue({
        ...stemReadyTranscription,
        title: "Drum Result",
        selected_stem: "drums",
        processing_status: "completed",
        notes_data: drumNotes,
        can_generate_score: false,
        can_generate_rhythm: true,
      });
    (audioService.listInstrumentTracks as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValue([
        {
          id: 7,
          transcription_id: 42,
          instrument_type: "drums",
          display_name: "Drums",
          notes_json: drumNotes,
          processing_status: "completed",
          created_at: "2026-05-20T00:00:00Z",
        },
      ]);

    render(<TranscriptionViewer />);

    expect(await screen.findByText("Drum Tabs")).toBeInTheDocument();
    expect(screen.getByText("HH|")).toBeInTheDocument();
    expect(screen.getByText("SD|")).toBeInTheDocument();
    expect(screen.getByText("BD|")).toBeInTheDocument();
  });

  it("shows vocal lyrics generation without switching to audio processing UI", async () => {
    (audioService.getTranscriptionResult as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValue({
        ...stemReadyTranscription,
        title: "Vocal Result",
        selected_stem: "vocals",
        processing_status: "stem_ready",
        lyrics_generation_status: null,
      });
    (audioService.listInstrumentTracks as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValue([]);

    render(<TranscriptionViewer />);

    const lyricsButton = await screen.findByRole("button", {
      name: /Generate Lyrics/i,
    });
    expect(
      screen.queryByRole("button", { name: /Generate Tabs/i }),
    ).not.toBeInTheDocument();

    fireEvent.click(lyricsButton);

    await waitFor(() => {
      expect(audioService.generateLyrics).toHaveBeenCalledWith(42, "test-token");
      expect(screen.getAllByText(/Generating lyrics\.\.\./i).length).toBeGreaterThan(0);
    });

    expect(
      screen.queryByText(/Preparing your score, tabs, and playback workspace/i),
    ).not.toBeInTheDocument();
  });
});
