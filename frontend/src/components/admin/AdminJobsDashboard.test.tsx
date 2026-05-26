import "@testing-library/jest-dom";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminJobsDashboard from "./AdminJobsDashboard";
import audioService from "../../services/audioService";
import {
  ADMIN_MODE_STORAGE_KEY,
  ADMIN_TOKEN_STORAGE_KEY,
} from "../../utils/adminAccess";

vi.mock("../../services/audioService", () => ({
  default: {
    listAdminJobs: vi.fn(),
    listAdminJobHistory: vi.fn(),
  },
}));

const mockJobsResponse = {
  jobs: [
    {
      id: 11,
      title: "Active stem job",
      selected_stem: "other",
      processing_status: "processing",
      modal_job_type: "process",
      modal_dispatch_status: "dispatched",
      modal_status_detail: "dispatched",
      modal_request_id: "modal-active",
      modal_retry_count: 0,
      created_at: "2026-05-26T10:00:00Z",
      updated_at: "2026-05-26T10:01:00Z",
      user_email: "active@example.com",
    },
  ],
  counts: {
    active: 1,
    queued: 0,
    processing: 1,
    rate_limited: 0,
  },
};

const mockHistoryResponse = {
  jobs: [
    {
      id: 22,
      title: "Completed history job",
      selected_stem: "bass",
      processing_status: "completed",
      modal_job_type: "process",
      modal_dispatch_status: "completed",
      modal_status_detail: "callback_completed",
      modal_request_id: "modal-complete",
      modal_retry_count: 1,
      duration_seconds: 44,
      created_at: "2026-05-26T09:00:00Z",
      updated_at: "2026-05-26T09:01:00Z",
      user_email: "history@example.com",
    },
  ],
  count: 1,
};

const mockedAudioService = audioService as unknown as {
  listAdminJobs: ReturnType<typeof vi.fn>;
  listAdminJobHistory: ReturnType<typeof vi.fn>;
};

const renderWithSavedToken = async () => {
  window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, "saved-admin-token");
  render(<AdminJobsDashboard />);
  await waitFor(() => {
    expect(mockedAudioService.listAdminJobs).toHaveBeenCalledWith(
      "saved-admin-token",
    );
  });
};

describe("AdminJobsDashboard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    mockedAudioService.listAdminJobs.mockResolvedValue(mockJobsResponse);
    mockedAudioService.listAdminJobHistory.mockResolvedValue(mockHistoryResponse);
  });

  it("shows a short backend token hint before an admin token is saved", () => {
    render(<AdminJobsDashboard />);

    expect(
      screen.getByText(
        "Enter the backend ADMIN_API_TOKEN to view operations jobs.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an actionable message when the backend admin API is disabled", async () => {
    mockedAudioService.listAdminJobs.mockRejectedValue({
      response: {
        status: 503,
        data: { detail: "Admin API is not configured." },
      },
    });

    window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, "saved-admin-token");
    render(<AdminJobsDashboard />);

    expect(
      await screen.findByText(
        "Admin API is disabled on this backend (503). Set ADMIN_API_TOKEN and restart the backend so startup logs show Admin API configured=True.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a stale-token hint when the admin token is rejected", async () => {
    mockedAudioService.listAdminJobs.mockRejectedValue({
      response: {
        status: 403,
        data: { detail: "Invalid admin token." },
      },
    });

    window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, "old-admin-token");
    render(<AdminJobsDashboard />);

    expect(
      await screen.findByText(
        "Invalid admin token (403). Use Forget admin token, then paste the current backend ADMIN_API_TOKEN.",
      ),
    ).toBeInTheDocument();
    expect(mockedAudioService.listAdminJobs).toHaveBeenCalledWith(
      "old-admin-token",
    );
  });

  it("shows the backend URL when the admin request times out", async () => {
    mockedAudioService.listAdminJobs.mockRejectedValue({
      code: "ECONNABORTED",
      message: "timeout of 10000ms exceeded",
    });

    window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, "saved-admin-token");
    render(<AdminJobsDashboard />);

    expect(
      await screen.findByText(
        "Admin jobs request timed out. Confirm the backend is running at http://localhost:8000/api/v1 and try again.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a network and CORS hint when the admin API cannot be reached", async () => {
    mockedAudioService.listAdminJobs.mockRejectedValue({
      request: {},
    });

    window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, "saved-admin-token");
    render(<AdminJobsDashboard />);

    expect(
      await screen.findByText(
        "Could not reach the admin API at http://localhost:8000/api/v1. Check that the backend is running and CORS allows this frontend.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps backend detail text for generic admin errors", async () => {
    mockedAudioService.listAdminJobs.mockRejectedValue({
      response: {
        status: 500,
        data: { detail: "Database connection failed." },
      },
    });

    window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, "saved-admin-token");
    render(<AdminJobsDashboard />);

    expect(
      await screen.findByText("Database connection failed. (500)"),
    ).toBeInTheDocument();
  });

  it("does not flash a timeout alert for a background refresh after a successful load", async () => {
    let intervalHandler: TimerHandler | undefined;
    const setIntervalSpy = vi
      .spyOn(window, "setInterval")
      .mockImplementation(((handler: TimerHandler, timeout?: number) => {
        if (timeout === 30000) {
          intervalHandler = handler;
        }
        return 1 as unknown as ReturnType<typeof window.setInterval>;
      }) as unknown as typeof window.setInterval);
    const clearIntervalSpy = vi
      .spyOn(window, "clearInterval")
      .mockImplementation(() => undefined);
    mockedAudioService.listAdminJobs
      .mockResolvedValueOnce(mockJobsResponse)
      .mockRejectedValueOnce({
        code: "ECONNABORTED",
        message: "timeout of 15000ms exceeded",
      });

    try {
      window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, "saved-admin-token");
      render(<AdminJobsDashboard />);

      expect(await screen.findByText("Active stem job")).toBeInTheDocument();

      expect(intervalHandler).toEqual(expect.any(Function));
      await act(async () => {
        await (intervalHandler as () => void)();
      });

      await waitFor(() => {
        expect(mockedAudioService.listAdminJobs).toHaveBeenCalledTimes(2);
      });
      expect(screen.queryByText(/Admin jobs request timed out/i)).not.toBeInTheDocument();
    } finally {
      setIntervalSpy.mockRestore();
      clearIntervalSpy.mockRestore();
    }
  });

  it("calls listAdminJobHistory with the selected history status", async () => {
    await renderWithSavedToken();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    await waitFor(() => {
      expect(mockedAudioService.listAdminJobHistory).toHaveBeenLastCalledWith(
        "saved-admin-token",
        { status: undefined, limit: 50 },
      );
    });

    fireEvent.change(screen.getByLabelText("Filter history by status"), {
      target: { value: "completed_with_warning" },
    });

    await waitFor(() => {
      expect(mockedAudioService.listAdminJobHistory).toHaveBeenLastCalledWith(
        "saved-admin-token",
        { status: "completed_with_warning", limit: 50 },
      );
    });
  });

  it("calls listAdminJobHistory with the selected history limit", async () => {
    await renderWithSavedToken();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    await waitFor(() => {
      expect(mockedAudioService.listAdminJobHistory).toHaveBeenLastCalledWith(
        "saved-admin-token",
        { status: undefined, limit: 50 },
      );
    });

    fireEvent.change(screen.getByLabelText("Limit history jobs"), {
      target: { value: "100" },
    });

    await waitFor(() => {
      expect(mockedAudioService.listAdminJobHistory).toHaveBeenLastCalledWith(
        "saved-admin-token",
        { status: undefined, limit: 100 },
      );
    });
  });

  it("forgets only the admin token and clears loaded dashboard data", async () => {
    window.localStorage.setItem(ADMIN_MODE_STORAGE_KEY, "enabled");
    await renderWithSavedToken();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(await screen.findByText("Completed history job")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Forget admin token" }));

    expect(window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(ADMIN_MODE_STORAGE_KEY)).toBe("enabled");
    expect(screen.getByLabelText("Admin token")).toHaveValue("");
    expect(screen.queryByText("Completed history job")).not.toBeInTheDocument();
    expect(screen.getByText("No history yet")).toBeInTheDocument();
    expect(screen.queryByText(/Synced/i)).not.toBeInTheDocument();
  });
});
