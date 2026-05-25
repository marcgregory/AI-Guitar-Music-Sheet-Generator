import { describe, expect, it, vi } from "vitest";

const mockApiClient = vi.hoisted(() => ({
  delete: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("./apiClient", () => ({
  API_ORIGIN: "http://localhost:8000",
  apiClient: mockApiClient,
  default: mockApiClient,
}));

import audioService from "./audioService";
import { apiClient } from "./apiClient";

describe("audioService", () => {
  it("posts track reprocessing requests to the explicit track endpoint", async () => {
    const postMock = vi.mocked(apiClient.post);
    postMock.mockResolvedValueOnce({
      data: {
        id: 4,
        transcription_id: 42,
        instrument_type: "guitar",
        display_name: "Guitar",
        processing_status: "processing",
        created_at: "2026-05-25T00:00:00",
      },
    });

    await audioService.reprocessInstrumentTrack(42, 4, "test-token");

    expect(postMock).toHaveBeenCalledWith(
      "/audio/42/tracks/4/reprocess",
      {},
    );
  });
});
