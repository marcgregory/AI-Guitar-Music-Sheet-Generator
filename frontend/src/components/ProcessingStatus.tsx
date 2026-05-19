import React, { useState, useEffect, useRef } from "react";
import audioService, {
  type ProcessingStatusValue,
} from "../services/audioService";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Icon } from "./Icon";

const ProcessingStatus: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [status, setStatus] = useState<"idle" | ProcessingStatusValue>("idle");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [canPlayStem, setCanPlayStem] = useState(false);
  const [canGenerateScore, setCanGenerateScore] = useState(true);
  const [isDemo, setIsDemo] = useState(false);
  const WAITING_FOR_MODAL_CAPACITY_MESSAGE =
    "Waiting for Modal capacity. Retry scheduled.";
  const [selectedStem, setSelectedStem] = useState<string | null>(null);
  const transcriptionIdNumRef = useRef<number | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
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

  useEffect(() => {
    if (transcriptionId) {
      const idNum = parseInt(transcriptionId, 10);
      if (!isNaN(idNum)) {
        transcriptionIdNumRef.current = idNum;
        checkTranscriptionStatus();

        // Set up polling to check status every 2 seconds
        const interval = setInterval(() => {
          checkTranscriptionStatus();
        }, 2000);

        return () => clearInterval(interval);
      }
    }
    navigate("/dashboard");
  }, [transcriptionId, token, navigate]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsMenuOpen(false);
        setShowDeleteDialog(false);
        setShowErrorDialog(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  const checkTranscriptionStatus = async () => {
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
    } catch (err: any) {
      setStatus("failed");
      setError(
        err.response?.data?.detail || "Failed to check transcription status",
      );
    }
  };

  const showToast = (tone: "success" | "error", message: string) => {
    setToast({ tone, message });
    window.setTimeout(() => setToast(null), 3600);
  };

  const handleDelete = async () => {
    if (!token || transcriptionIdNumRef.current === null) return;
    setIsDeleting(true);
    try {
      await audioService.deleteTranscription(transcriptionIdNumRef.current, token);
      showToast("success", "Transcription deleted.");
      setShowDeleteDialog(false);
      window.setTimeout(() => navigate("/dashboard"), 450);
    } catch (err: any) {
      showToast(
        "error",
        err.response?.data?.detail || "Could not delete transcription.",
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
    } catch (err: any) {
      showToast(
        "error",
        err.response?.data?.detail || "Could not retry transcription.",
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
    } catch (err: any) {
      showToast(
        "error",
        err.response?.data?.detail || "Demo transcription is not available.",
      );
    }
  };

  const statusActionLabel =
    status === "queued" || status === "pending"
      ? "View queue status"
      : "View progress";

  const isWaitingForModalCapacity =
    status === "queued" && statusMessage === WAITING_FOR_MODAL_CAPACITY_MESSAGE;

  const canShowProcessingMenu =
    !isDemo &&
    (status === "pending" ||
      status === "queued" ||
      status === "processing" ||
      status === "stem_ready" ||
      status === "completed" ||
      status === "completed_with_warning" ||
      status === "failed");

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
        {canShowProcessingMenu && (
          <div className="project-menu-shell processing-menu-shell">
            <button
              type="button"
              className={`project-more-button ${isMenuOpen ? "active" : ""}`}
              aria-label="Processing actions"
              aria-haspopup="menu"
              aria-expanded={isMenuOpen}
              onClick={() => setIsMenuOpen((open) => !open)}
            >
              <Icon name="more" />
            </button>
            {isMenuOpen && (
              <div className="project-action-menu" role="menu">
                {(status === "pending" ||
                  status === "queued" ||
                  status === "processing") && (
                  <button
                    type="button"
                    role="menuitem"
                    className="project-action-menu-item"
                    onClick={() => setIsMenuOpen(false)}
                  >
                    <Icon name={status === "processing" ? "eye" : "clock"} />
                    <span>{statusActionLabel}</span>
                  </button>
                )}
                {status === "failed" && (
                  <button
                    type="button"
                    role="menuitem"
                    className="project-action-menu-item"
                    onClick={() => {
                      setIsMenuOpen(false);
                      setShowErrorDialog(true);
                    }}
                  >
                    <Icon name="alert" />
                    <span>View processing error</span>
                  </button>
                )}
                <button
                  type="button"
                  role="menuitem"
                  className="project-action-menu-item danger"
                  onClick={() => {
                    setIsMenuOpen(false);
                    setShowDeleteDialog(true);
                  }}
                >
                  <Icon name="trash" />
                  <span>Delete project</span>
                </button>
              </div>
            )}
          </div>
        )}
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
              <p>
                Stem is ready. Listen first, then generate tabs if the stem
                sounds useful.
              </p>
              <p>
                Tab generation will only run after you confirm from the preview
                screen.
              </p>
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
              onClick={() => navigate(`/transcription/${transcriptionIdNumRef.current}`)}
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
