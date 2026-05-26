import React, { useState, useEffect, useRef, useCallback } from "react";
import audioService, {
  type ProcessingStatusValue,
} from "../services/audioService";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Icon } from "./Icon";
import { getStemLimitationNotice } from "../utils/transcriptionMetadata";

type ModalDiagnostics = {
  modal_status_detail?: string | null;
  modal_dispatch_status?: string | null;
  modal_request_id?: string | null;
  modal_retry_count?: number | null;
  modal_retry_at?: string | null;
};

const MODAL_STATUS_LABELS: Record<string, string> = {
  queued_waiting_for_active_job: "Queued behind another active job",
  dispatched: "Dispatched to Modal",
  rate_limited_retry: "Modal rate-limited; retry scheduled",
  callback_completed: "Worker callback received",
  dispatch_failed: "Modal dispatch failed",
  rate_limited: "Modal rate-limited",
  retry_queued: "Modal retry queued",
  completed: "Worker callback received",
  failed: "Modal dispatch failed",
};

const formatModalState = (value: string | null | undefined): string | null => {
  if (!value) return null;
  return (
    MODAL_STATUS_LABELS[value] ??
    value
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ")
  );
};

const formatRetryAt = (value: string | null | undefined): string | null => {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
};

const hasModalDiagnostics = (diagnostics: ModalDiagnostics): boolean =>
  Boolean(
    diagnostics.modal_status_detail ||
      diagnostics.modal_dispatch_status ||
      diagnostics.modal_request_id ||
      diagnostics.modal_retry_count ||
      diagnostics.modal_retry_at,
  );

const getErrorDetail = (error: unknown, fallback: string): string => {
  if (
    typeof error === "object" &&
    error !== null &&
    "response" in error &&
    typeof error.response === "object" &&
    error.response !== null &&
    "data" in error.response &&
    typeof error.response.data === "object" &&
    error.response.data !== null &&
    "detail" in error.response.data &&
    typeof error.response.data.detail === "string"
  ) {
    return error.response.data.detail;
  }
  return fallback;
};

const ProcessingStatus: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [status, setStatus] = useState<"idle" | ProcessingStatusValue>("idle");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [modalDiagnostics, setModalDiagnostics] = useState<ModalDiagnostics>(
    {},
  );
  const [canPlayStem, setCanPlayStem] = useState(false);
  const [canGenerateScore, setCanGenerateScore] = useState(true);
  const [isDemo, setIsDemo] = useState(false);
  const WAITING_FOR_MODAL_CAPACITY_MESSAGE =
    "Waiting for Modal capacity. Retry scheduled.";
  const [selectedStem, setSelectedStem] = useState<string | null>(null);
  const transcriptionIdNumRef = useRef<number | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showErrorDialog, setShowErrorDialog] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [toast, setToast] = useState<{
    tone: "success" | "error";
    message: string;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();
  const { token } = useAuth();
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const checkTranscriptionStatus = useCallback(async () => {
    if (!token) return;
    const id = transcriptionIdNumRef.current;
    if (id === null) return;

    try {
      const response = await audioService.getTranscriptionStatus(id, token);
      setSelectedStem(response.selected_stem ?? null);
      setStatusMessage(response.message ?? null);
      setWarning(response.warning ?? null);
      setCanPlayStem(Boolean(response.can_play_stem));
      setCanGenerateScore(response.can_generate_score !== false);
      setIsDemo(Boolean(response.is_demo));
      setModalDiagnostics({
        modal_status_detail: response.modal_status_detail ?? null,
        modal_dispatch_status: response.modal_dispatch_status ?? null,
        modal_request_id: response.modal_request_id ?? null,
        modal_retry_count: response.modal_retry_count ?? null,
        modal_retry_at: response.modal_retry_at ?? null,
      });

      // Check if we've reached a terminal state and stop polling if so
      const isTerminalState =
        response.status === "completed" ||
        response.status === "completed_with_warning" ||
        response.status === "stem_ready" ||
        response.status === "failed" ||
        response.status === "cancelled" ||
        response.status === "deleted";

      if (isTerminalState) {
        // Clear polling interval when we reach a terminal state
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
      }

      if (response.status === "completed" || response.status === "stem_ready") {
        setStatus(response.status);
        setProgress(100);
        if (response.can_generate_score !== false) {
          setTimeout(() => {
            navigate(`/transcription/${id}`);
          }, 1500);
        }
      } else if (response.status === "failed") {
        setStatus("failed");
        setError(response.error || "Processing failed");
      } else {
        setStatus(response.status);
        setProgress(
          typeof response.progress === "number" ? response.progress : null,
        );
      }
    } catch (err: unknown) {
      setStatus("failed");
      setError(getErrorDetail(err, "Failed to check transcription status"));
      // Also clear polling interval on error to prevent unnecessary polling
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    }
  }, [token, navigate]);

  useEffect(() => {
    if (transcriptionId) {
      const idNum = parseInt(transcriptionId, 10);
      if (!isNaN(idNum)) {
        transcriptionIdNumRef.current = idNum;
        checkTranscriptionStatus();

        // Set up polling to check status every 2 seconds
        pollingIntervalRef.current = setInterval(() => {
          checkTranscriptionStatus();
        }, 2000);

        return () => {
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
          }
        };
      }
    }
    navigate("/dashboard");
  }, [transcriptionId, checkTranscriptionStatus, navigate]);

  const showToast = (tone: "success" | "error", message: string) => {
    setToast({ tone, message });
    window.setTimeout(() => setToast(null), 3600);
  };

  const handleDelete = async () => {
    if (!token || transcriptionIdNumRef.current === null) return;
    setIsDeleting(true);
    try {
      await audioService.deleteTranscription(
        transcriptionIdNumRef.current,
        token,
      );
      showToast("success", "Transcription deleted.");
      setShowDeleteDialog(false);
      window.setTimeout(() => navigate("/dashboard"), 450);
    } catch (err: unknown) {
      showToast(
        "error",
        getErrorDetail(err, "Could not delete transcription."),
      );
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRetry = async () => {
    if (!token || transcriptionIdNumRef.current === null) return;
    setIsRetrying(true);
    try {
      const response = await audioService.retryTranscription(
        transcriptionIdNumRef.current,
        token,
        {
          lower_threshold: true,
        },
      );
      setStatus(response.status);
      setWarning(response.warning ?? null);
      setStatusMessage(response.message ?? null);
      setError(null);
      showToast("success", "Retry queued with lower note threshold.");
    } catch (err: unknown) {
      showToast(
        "error",
        getErrorDetail(err, "Could not retry transcription."),
      );
    } finally {
      setIsRetrying(false);
    }
  };

  const handleViewExampleTab = async () => {
    if (!token) return;
    try {
      const demo = await audioService.getDemoTranscription(token);
      navigate(`/transcription/${demo.id}`);
    } catch (err: unknown) {
      showToast(
        "error",
        getErrorDetail(err, "Demo transcription is not available."),
      );
    }
  };

  const isWaitingForModalCapacity =
    status === "queued" && statusMessage === WAITING_FOR_MODAL_CAPACITY_MESSAGE;

  const modalDiagnosticItems = [
    {
      label: "Status detail",
      value: formatModalState(modalDiagnostics.modal_status_detail),
    },
    {
      label: "Dispatch status",
      value: formatModalState(modalDiagnostics.modal_dispatch_status),
    },
    { label: "Request ID", value: modalDiagnostics.modal_request_id },
    {
      label: "Retry count",
      value:
        typeof modalDiagnostics.modal_retry_count === "number"
          ? modalDiagnostics.modal_retry_count.toString()
          : null,
    },
    {
      label: "Retry at",
      value: formatRetryAt(modalDiagnostics.modal_retry_at),
    },
  ].filter(
    (item): item is { label: string; value: string } =>
      typeof item.value === "string" && item.value.length > 0,
  );

  const stemReadyCopy = (() => {
    if (selectedStem === "drums") {
      return {
        ready:
          "Drum stem is ready. Listen first, then generate rhythm if the stem sounds useful.",
        followup: getStemLimitationNotice(selectedStem),
      };
    }
    if (selectedStem === "vocals") {
      return {
        ready:
          "Vocal stem is ready. Listen first, then generate lyrics when you want a timestamped transcription.",
        followup: getStemLimitationNotice(selectedStem),
      };
    }
    return {
      ready:
        "Stem is ready. Listen first, then generate tabs if the stem sounds useful.",
      followup: getStemLimitationNotice(selectedStem),
    };
  })();

  if (status === "idle") {
    return (
      <div className="processing-status-container">
        <div className="processing-status-header">
          <h2>Processing Your Audio</h2>
          <p>We're analyzing your audio file to generate guitar tabs</p>
        </div>
        <div className="processing-status-content">
          <div className="processing-spinner"></div>
          <p className="processing-text">Preparing upload...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="processing-status-container" ref={containerRef}>
      {toast && (
        <div className={`studio-toast studio-toast-${toast.tone}`}>
          {toast.message}
        </div>
      )}
      <div className="processing-status-header">
        <div>
          <h2>Processing Your Audio</h2>
          <p>
            {selectedStem
              ? `Selected stem: ${selectedStem === "other" ? "Other / Guitar / Piano / Melody" : selectedStem}`
              : "We're preparing your selected-stem analysis"}
          </p>
        </div>
      </div>

      {(status === "pending" ||
        status === "queued" ||
        status === "processing") && (
        <div className="processing-status-content">
          <div className="processing-info">
            {isWaitingForModalCapacity ? (
              <div className="modal-capacity-waiting">
                <div className="progress-label">Waiting for Modal capacity</div>
                <p>{statusMessage}</p>
              </div>
            ) : (
              <>
                <div className="progress-section">
                  <div className="progress-label">
                    {status === "queued"
                      ? "Queued"
                      : status === "pending"
                        ? "Pending"
                        : "Processing Progress"}
                  </div>
                  <div className="progress-bar">
                    <div
                      className={`progress-fill ${progress === null ? "indeterminate" : ""}`}
                      style={{
                        width: progress === null ? undefined : `${progress}%`,
                      }}
                    ></div>
                  </div>
                  <p className="progress-percent">
                    {status === "queued"
                      ? "Waiting for the worker"
                      : progress === null
                        ? "Processing..."
                        : `${progress}%`}
                  </p>
                </div>

                {progress !== null && (
                  <div className="estimated-time">
                    <div className="time-label">Estimated Time Remaining</div>
                    <div className="time-value">
                      <span>
                        ~{Math.max(1, Math.round((100 - progress) / 10))} min
                      </span>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="processing-details">
            {statusMessage && !isWaitingForModalCapacity && (
              <p>{statusMessage}</p>
            )}
            <p>
              This process may take several minutes depending on the length and
              complexity of your audio file.
            </p>
            <p>
              You can safely close this tab and return later to check whether it
              is queued, processing, failed, or completed.
            </p>
          </div>
        </div>
      )}

      {(status === "stem_ready" ||
        status === "completed" ||
        status === "completed_with_warning") && (
        <div
          className={`processing-status-content ${canGenerateScore ? "processing-success" : "processing-warning"}`}
        >
          <div
            className={canGenerateScore ? "success-icon" : "warning-icon"}
            aria-hidden="true"
          ></div>
          <h3>
            {canGenerateScore ? "Processing complete" : "Stem preview ready"}
          </h3>
          {canGenerateScore ? (
            <p>
              Your audio has been successfully processed and transcribed into
              guitar tabs.
            </p>
          ) : status === "stem_ready" ? (
            <>
              <p>{stemReadyCopy.ready}</p>
              <p>{stemReadyCopy.followup}</p>
            </>
          ) : (
            <>
              <p>
                {warning ||
                  "Stem separated successfully, but no playable notes were detected for notation generation."}
              </p>
              <p>You can still preview the isolated stem audio.</p>
            </>
          )}
          <div className="processing-actions">
            <button
              className="button-primary"
              onClick={() =>
                navigate(`/transcription/${transcriptionIdNumRef.current}`)
              }
            >
              {canGenerateScore
                ? "View Transcription"
                : canPlayStem
                  ? "Preview isolated stem"
                  : "Open result"}
            </button>
            {!canGenerateScore && (
              <>
                {!isDemo && (
                  <button
                    className="button-secondary"
                    disabled={isRetrying}
                    onClick={handleRetry}
                  >
                    {isRetrying ? "Queuing retry..." : "Retry transcription"}
                  </button>
                )}
                <button
                  className="button-secondary"
                  onClick={handleViewExampleTab}
                >
                  View example TAB
                </button>
                <button
                  className="button-secondary"
                  onClick={() => navigate("/upload")}
                >
                  Choose another stem
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {status === "failed" && (
        <div className="processing-status-content processing-error">
          <div className="error-icon" aria-hidden="true"></div>
          <h3>Processing failed</h3>
          <p>{error || "An error occurred during processing"}</p>
          <div className="processing-actions">
            <button
              className="button-secondary"
              onClick={() => navigate("/dashboard")}
            >
              Return to Dashboard
            </button>
            <button
              className="button-primary"
              onClick={() => {
                // Retry processing - in a real app, this would restart the process
                navigate(`/upload`);
              }}
            >
              Try Again
            </button>
          </div>
        </div>
      )}

      {hasModalDiagnostics(modalDiagnostics) && (
        <section
          className="modal-diagnostics-panel"
          aria-label="Modal diagnostics"
        >
          <div className="modal-diagnostics-heading">
            <span>Modal diagnostics</span>
          </div>
          <dl className="modal-diagnostics-grid">
            {modalDiagnosticItems.map((item) => (
              <div className="modal-diagnostics-row" key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {showDeleteDialog && (
        <div className="studio-modal-backdrop" role="presentation">
          <div
            className="studio-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-processing-title"
          >
            <h3 id="delete-processing-title">Delete transcription</h3>
            <p>Are you sure you want to delete this transcription?</p>
            {status === "processing" && (
              <p className="studio-dialog-warning">
                Active processing cancellation is best-effort and may finish
                silently.
              </p>
            )}
            <div className="studio-dialog-actions">
              <button
                type="button"
                className="button-secondary"
                disabled={isDeleting}
                onClick={() => setShowDeleteDialog(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="button-danger"
                disabled={isDeleting}
                onClick={handleDelete}
              >
                <Icon name="trash" />
                <span>{isDeleting ? "Deleting..." : "Delete project"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {showErrorDialog && (
        <div className="studio-modal-backdrop" role="presentation">
          <div
            className="studio-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="processing-error-title"
          >
            <h3 id="processing-error-title">Processing error</h3>
            <p>{error || "No detailed processing error was returned."}</p>
            <div className="studio-dialog-actions">
              <button
                type="button"
                className="button-primary"
                onClick={() => setShowErrorDialog(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProcessingStatus;
