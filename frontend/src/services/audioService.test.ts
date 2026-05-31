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

import audioService, {
  getDailyProcessingLimitMessage,
  getDailyProcessingLimitUsage,
  isDailyProcessingLimitError,
} from "./audioService";
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

  it("times out transcription library requests instead of waiting forever", async () => {
    const getMock = vi.mocked(apiClient.get);
    getMock.mockResolvedValueOnce({ data: [] });

    await audioService.listTranscriptions("test-token");

    expect(getMock).toHaveBeenCalledWith("/audio/", {
      timeout: 15000,
    });
  });

  it("passes admin usage filters as query params", async () => {
    const getMock = vi.mocked(apiClient.get);
    getMock.mockResolvedValueOnce({ data: { date: "2026-05-27", usage: [] } });

    await audioService.listAdminUsage("admin-token", {
      userId: 123,
      date: "2026-05-27",
    });

    expect(getMock).toHaveBeenCalledWith("/admin/usage", {
      headers: { "X-Admin-Token": "admin-token" },
      params: {
        user_id: 123,
        date: "2026-05-27",
      },
      timeout: 15000,
    });
  });

  it("posts admin usage reset requests without touching jobs", async () => {
    const postMock = vi.mocked(apiClient.post);
    postMock.mockResolvedValueOnce({
      data: {
        success: true,
        deleted_count: 5,
        usage: {
          user_id: 123,
          username: "markyturns",
          usage_count: 0,
          daily_limit: 5,
          remaining_quota: 5,
          active_job_count: 0,
          reset_available: true,
        },
      },
    });

    await audioService.resetAdminUsage("admin-token", 123);

    expect(postMock).toHaveBeenCalledWith(
      "/admin/usage/reset",
      { user_id: 123 },
      {
        headers: { "X-Admin-Token": "admin-token" },
        timeout: 15000,
      },
    );
  });

  it("recognizes legacy string daily processing limit errors", () => {
    const error = {
      response: {
        status: 429,
        data: {
          detail: "Daily processing limit reached. Please try again tomorrow.",
        },
      },
    };

    expect(isDailyProcessingLimitError(error)).toBe(true);
    expect(getDailyProcessingLimitMessage(error)).toBeNull();
    expect(getDailyProcessingLimitUsage(error)).toBeNull();
  });

  it("extracts structured daily processing limit detail safely", () => {
    const usage = {
      usage_count: 1,
      daily_limit: 1,
      remaining_quota: 0,
      resets_at: "2026-05-28T00:00:00Z",
      is_unlimited: false,
    };
    const error = {
      response: {
        status: 429,
        data: {
          detail: {
            error: "Daily processing limit reached.",
            message:
              "Your daily processing attempts are used. Quota resets at 00:00 UTC.",
            usage,
          },
        },
      },
    };

    expect(isDailyProcessingLimitError(error)).toBe(true);
    expect(getDailyProcessingLimitMessage(error)).toBe(
      "Your daily processing attempts are used. Quota resets at 00:00 UTC.",
    );
    expect(getDailyProcessingLimitUsage(error)).toEqual(usage);
  });
});
