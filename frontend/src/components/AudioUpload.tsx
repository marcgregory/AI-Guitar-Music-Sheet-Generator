import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import gsap from "gsap";
import {
  AudioWaveform,
  CloudUpload,
  Clock3,
  Folder,
  Guitar,
  Lightbulb,
  Mic2,
  RotateCw,
  ShieldCheck,
  SlidersHorizontal,
  UsersRound,
  Video,
} from "lucide-react";
import audioService, {
  type StemSelection,
  type Transcription,
} from "../services/audioService";
import { getStemLimitationNotice } from "../utils/transcriptionMetadata";
import { useAuth } from "./auth/AuthContext";

const AudioUpload: React.FC = () => {
  const { token } = useAuth();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const waveRef = useRef<HTMLDivElement | null>(null);
  const cloudRef = useRef<HTMLDivElement | null>(null);
  const dropzoneRef = useRef<HTMLDivElement | null>(null);
  const uploadNoteRef = useRef<HTMLDivElement | null>(null);
  const uploadIconRef = useRef<HTMLDivElement | null>(null);
  const uploadParticleRef = useRef<HTMLSpanElement | null>(null);
  const [activeTab, setActiveTab] = useState<"file" | "youtube">("file");
  const [file, setFile] = useState<File | null>(null);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [selectedStem, setSelectedStem] = useState<StemSelection | "">("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(0);
  const [isActiveTranscriptionLoading, setIsActiveTranscriptionLoading] =
    useState(true);
  const [processingSlotBusy, setProcessingSlotBusy] = useState(false);
  const [isCheckingSlot, setIsCheckingSlot] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduceMotion) return;

    const ctx = gsap.context(() => {
      gsap.from(".audio-upload-stage", {
        y: 34,
        opacity: 0,
        duration: 0.9,
        ease: "power3.out",
      });

      gsap.from(".upload-headline-line", {
        y: 44,
        opacity: 0,
        duration: 0.9,
        stagger: 0.14,
        delay: 0.2,
        ease: "power4.out",
      });

      gsap.from(".transcription-upload-shell", {
        y: 36,
        opacity: 0,
        duration: 0.85,
        delay: 0.46,
        ease: "power3.out",
      });

      gsap.to(waveRef.current, {
        x: -34,
        y: 12,
        duration: 7,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.to(cloudRef.current, {
        scale: 1.045,
        duration: 1.8,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.to(dropzoneRef.current, {
        boxShadow:
          "0 0 0 1px rgba(249, 115, 22, 0.14), inset 0 0 44px rgba(249, 115, 22, 0.08)",
        duration: 2.2,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
    }, rootRef);

    return () => ctx.revert();
  }, []);

  const isNonBlockingProcessingWarning = (error?: string | null): boolean =>
    Boolean(
      error?.startsWith(
        "Source separation unavailable; processed the full mix instead.",
      ),
    );

  useEffect(() => {
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduceMotion || !uploadNoteRef.current) return;

    const ctx = gsap.context(() => {
      if (!isUploading) {
        gsap.to(uploadNoteRef.current, {
          y: 0,
          scale: 1,
          duration: 0.45,
          ease: "power2.out",
        });
        gsap.to(".upload-waveform-glyph", {
          scale: 1,
          opacity: 1,
          duration: 0.35,
          ease: "power2.out",
        });
        return;
      }

      gsap.to(uploadNoteRef.current, {
        y: -3,
        duration: 2.6,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.to(uploadIconRef.current, {
        scale: 1.045,
        duration: 1.45,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.to(".upload-waveform-glyph", {
        scale: 1.08,
        opacity: 0.86,
        duration: 0.72,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });

      gsap.to(uploadParticleRef.current, {
        rotate: 360,
        scale: 1.08,
        duration: 7,
        repeat: -1,
        ease: "none",
      });
    }, uploadNoteRef);

    return () => ctx.revert();
  }, [isUploading]);

  const hasBlockingActiveTranscription = (
    transcriptions: Transcription[],
  ): boolean =>
    transcriptions.some(
      (transcription: Transcription) =>
        !transcription.is_processed &&
        transcription.processing_status !== "failed" &&
        (!transcription.processing_error ||
          isNonBlockingProcessingWarning(transcription.processing_error)),
    );

  const loadActiveTranscriptions = useCallback(async (): Promise<boolean> => {
    if (!token) {
      setIsActiveTranscriptionLoading(false);
      return false;
    }

    try {
      const transcriptions = await audioService.listTranscriptions(token);
      const active = hasBlockingActiveTranscription(transcriptions);
      return active;
    } catch (error) {
      return false;
    } finally {
      setIsActiveTranscriptionLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadActiveTranscriptions();
  }, [loadActiveTranscriptions]);

  const fallbackErrorMessage = (err: any, fallback: string): string => {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (
      detail &&
      typeof detail === "object" &&
      typeof detail.error === "string"
    ) {
      return detail.error;
    }
    return err.message || fallback;
  };

  const showProcessingSlotBusy = () => {
    setProcessingSlotBusy(true);
    setError(null);
  };

  const clearProcessingSlotBusy = () => {
    setProcessingSlotBusy(false);
  };

  const handleCheckAgain = async () => {
    if (!token) {
      setError("Authentication error. Please log in again.");
      clearProcessingSlotBusy();
      return;
    }

    setIsCheckingSlot(true);
    setError(null);
    try {
      const active = await loadActiveTranscriptions();
      if (!active) {
        clearProcessingSlotBusy();
      }
    } finally {
      setIsCheckingSlot(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setError(null);
      setSuccess(null);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.add("dragover");
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove("dragover");
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove("dragover");

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      const fileExtension = `.${droppedFile.name?.split(".")?.pop()?.toLowerCase()}`;
      if ([".mp3", ".wav"].includes(fileExtension)) {
        setFile(droppedFile);
        setError(null);
        setSuccess(null);
      } else {
        setError("Only MP3 and WAV files are allowed");
        setFile(null);
      }
    }
  };

  const handleFileUpload = async () => {
    if (!file) {
      setError("Please select a file to upload");
      return;
    }

    if (!token) {
      setError("Authentication error. Please log in again.");
      return;
    }

    if (!selectedStem) {
      setError("Please choose one target stem before processing.");
      return;
    }

    if (isActiveTranscriptionLoading) {
      setError(
        "Checking transcription status. Please wait a moment before uploading.",
      );
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);
    setError(null);
    setSuccess(null);

    try {
      const response = await audioService.uploadAudioFile(
        file,
        token,
        selectedStem,
        undefined,
        (progress) => {
          setUploadProgress(Math.min(progress, 95));
        },
      );
      setUploadProgress(100);
      if (response.duplicate_reused) {
        setSuccess(
          response.duplicate_message ||
            "This song and stem were already processed. Existing result was loaded.",
        );
        setTimeout(() => {
          navigate(`/transcription/${response.id}`);
        }, 1200);
        return;
      }
      setSuccess(
        `File uploaded successfully. Transcription ID: ${response.id}`,
      );

      setTimeout(() => {
        navigate(`/processing/${response.id}`);
      }, 1500);
    } catch (err: any) {
      setUploadProgress(0);
      if (err.response?.status === 409) {
        showProcessingSlotBusy();
      } else {
        setError(fallbackErrorMessage(err, "Upload failed. Please try again."));
      }
    } finally {
      setIsUploading(false);
    }
  };

  const handleYoutubeSubmit = async () => {
    if (!youtubeUrl.trim()) {
      setError("Please enter a YouTube URL");
      return;
    }

    if (!token) {
      setError("Authentication error. Please log in again.");
      return;
    }

    if (!selectedStem) {
      setError("Please choose one target stem before processing.");
      return;
    }

    if (isActiveTranscriptionLoading) {
      setError(
        "Checking transcription status. Please wait a moment before extracting audio.",
      );
      return;
    }

    const youtubeRegex = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+/;
    if (!youtubeRegex.test(youtubeUrl)) {
      setError("Please enter a valid YouTube URL");
      return;
    }

    setIsUploading(true);
    setUploadProgress(null);
    setError(null);
    setSuccess(null);

    try {
      const response = await audioService.extractAudioFromYouTube(
        youtubeUrl,
        token,
        selectedStem,
      );
      setUploadProgress(100);
      if (response.duplicate_reused) {
        setSuccess(
          response.duplicate_message ||
            "This song and stem were already processed. Existing result was loaded.",
        );
        setTimeout(() => {
          navigate(`/transcription/${response.id}`);
        }, 1200);
        return;
      }
      setSuccess(
        `YouTube audio extracted successfully. Transcription ID: ${response.id}`,
      );

      setTimeout(() => {
        navigate(`/processing/${response.id}`);
      }, 1500);
    } catch (err: any) {
      setUploadProgress(0);
      if (err.response?.status === 409) {
        showProcessingSlotBusy();
      } else {
        setError(
          fallbackErrorMessage(
            err,
            "Failed to extract audio from YouTube. Please try again.",
          ),
        );
      }
    } finally {
      setIsUploading(false);
    }
  };

  const resetForm = () => {
    setFile(null);
    setYoutubeUrl("");
    setSelectedStem("");
    setUploadProgress(0);
    setError(null);
    setSuccess(null);
    setProcessingSlotBusy(false);
  };
  const fileUploadStatus = "Upload audio";
  const fileProgressValue = isUploading
    ? uploadProgress === null
      ? 35
      : Math.min(uploadProgress, 95)
    : file
      ? 0
      : 0;
  const uploadPercentLabel =
    isUploading && uploadProgress !== null
      ? `${Math.round(Math.max(0, Math.min(100, uploadProgress)))}%`
      : null;
  const fileUploadStatusDetail = uploadPercentLabel ?? "We'll handle the rest";
  const fileUploadDisabled =
    isUploading ||
    isActiveTranscriptionLoading ||
    processingSlotBusy ||
    !selectedStem;
  const youtubeSubmitDisabled =
    isUploading ||
    !youtubeUrl.trim() ||
    isActiveTranscriptionLoading ||
    processingSlotBusy ||
    !selectedStem;

  return (
    <div className="audio-upload-container" ref={rootRef}>
      <section className="audio-upload-stage">
        <div className="upload-wave-art" ref={waveRef} aria-hidden="true">
          <span className="upload-wave-curve upload-wave-curve-one" />
          <span className="upload-wave-curve upload-wave-curve-two" />
          <span className="upload-wave-curve upload-wave-curve-three" />
          <span className="upload-wave-curve upload-wave-curve-four" />
          <span className="upload-wave-glint" />
        </div>

        <header className="audio-upload-header">
          <h2 aria-label="Start a transcription">
            <span className="upload-headline-line">Start a</span>
            <span className="upload-headline-line upload-headline-accent">
              transcription
            </span>
          </h2>
          <span className="upload-header-divider" aria-hidden="true" />
          <p>
            Upload a clean guitar recording or extract audio from YouTube, then
            send it into the analysis pipeline.
          </p>
        </header>

        <div className="transcription-upload-shell">
          <div
            className="audio-upload-tabs"
            role="tablist"
            aria-label="Upload source"
          >
            <button
              type="button"
              className={`tab-button ${activeTab === "file" ? "active" : ""}`}
              onClick={() => setActiveTab("file")}
            >
              <CloudUpload aria-hidden="true" />
              File upload
            </button>
            <button
              type="button"
              className={`tab-button ${activeTab === "youtube" ? "active" : ""}`}
              onClick={() => setActiveTab("youtube")}
            >
              <Video aria-hidden="true" />
              YouTube URL
            </button>
          </div>

          <div className="upload-card">
            <div className="upload-primary-column">
              {isActiveTranscriptionLoading && !isUploading && (
                <div className="upload-lock-banner upload-info-banner">
                  <p>
                    Checking current transcription status. Please wait a moment.
                  </p>
                </div>
              )}
              <StemSelector
                selectedStem={selectedStem}
                onSelect={(stem) => {
                  setSelectedStem(stem);
                  setError(null);
                }}
              />
              {activeTab === "file" ? (
                <div
                  ref={dropzoneRef}
                  className="file-upload-area"
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  <div className="upload-orbit" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="cloud-upload-mark" ref={cloudRef}>
                    <CloudUpload aria-hidden="true" />
                  </div>
                  <p className="dropzone-title">Drop your audio file here</p>
                  <p className="file-upload-text">
                    or choose a file from your device
                  </p>
                  <button
                    type="button"
                    className="browse-button"
                    onClick={() =>
                      document.getElementById("file-input")?.click()
                    }
                    disabled={fileUploadDisabled}
                  >
                    <Folder aria-hidden="true" />
                    Browse files
                  </button>
                  <input
                    type="file"
                    id="file-input"
                    accept=".mp3,.wav"
                    hidden
                    onChange={handleFileChange}
                  />
                  <p className="file-limits">
                    Supported formats: MP3, WAV &bull; Maximum size: 100MB
                    &bull; Best under 5 minutes
                  </p>

                  {file && (
                    <div className="selected-file">
                      <span className="file-name">{file.name}</span>
                      <span className="file-size">
                        {(file.size / (1024 * 1024)).toFixed(2)} MB
                      </span>
                      <button
                        type="button"
                        className="remove-file-button"
                        onClick={() => setFile(null)}
                        disabled={isUploading}
                      >
                        Remove
                      </button>
                      <button
                        type="button"
                        className="upload-button"
                        onClick={handleFileUpload}
                        disabled={fileUploadDisabled}
                      >
                        {isUploading ? "Uploading..." : "Upload audio"}
                      </button>
                    </div>
                  )}

                  <div
                    ref={uploadNoteRef}
                    className={`upload-audio-note ${file ? "has-file" : ""} ${isUploading ? "is-uploading" : ""}`}
                    style={
                      {
                        "--upload-progress": `${fileProgressValue}%`,
                        "--upload-progress-ratio": fileProgressValue / 100,
                      } as React.CSSProperties
                    }
                  >
                    <div
                      className="upload-waveform-icon"
                      ref={uploadIconRef}
                      aria-hidden="true"
                    >
                      <span className="upload-icon-fill" />
                      <span
                        className="upload-icon-particles"
                        ref={uploadParticleRef}
                      />
                      <AudioWaveform
                        className="upload-waveform-glyph"
                        aria-hidden="true"
                      />
                    </div>
                    <span className="upload-audio-copy">
                      <span className="upload-status-row">
                        <strong>{fileUploadStatus}</strong>
                      </span>
                      <small>{fileUploadStatusDetail}</small>
                    </span>
                  </div>
                </div>
              ) : (
                <div className="youtube-upload-section">
                  <div className="youtube-input-group">
                    <Video aria-hidden="true" />
                    <input
                      type="text"
                      placeholder="Paste a YouTube URL"
                      value={youtubeUrl}
                      onChange={(e) => setYoutubeUrl(e.target.value)}
                      disabled={isUploading}
                    />
                    <button
                      type="button"
                      className="youtube-button"
                      onClick={handleYoutubeSubmit}
                      disabled={youtubeSubmitDisabled}
                    >
                      {isUploading ? "Processing..." : "Extract audio"}
                    </button>
                  </div>
                  <p className="youtube-help">
                    Use a public YouTube link with clear guitar audio for best
                    extraction results.
                  </p>
                </div>
              )}
              {processingSlotBusy && (
                <ProcessingSlotBusyCard
                  isChecking={isCheckingSlot}
                  onCheckAgain={handleCheckAgain}
                />
              )}
            </div>

            <aside className="upload-help-column" aria-label="Upload guidance">
              <HelpItem
                icon={<SlidersHorizontal aria-hidden="true" />}
                title="Clean audio = better results"
                body="Remove background noise for higher accuracy."
              />
              <HelpItem
                icon={<Guitar aria-hidden="true" />}
                title="Guitar recordings work best"
                body="Solo guitar or minimal background instruments."
              />
              <HelpItem
                icon={<ShieldCheck aria-hidden="true" />}
                title="Your files are private"
                body="We never share your audio or your transcriptions."
              />
            </aside>
          </div>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        {success && (
          <div className="alert alert-success">
            {success}
            <button
              type="button"
              className="close-alert"
              onClick={() => {
                setSuccess(null);
                resetForm();
              }}
            >
              Close
            </button>
          </div>
        )}
      </section>
    </div>
  );
};

const HelpItem = ({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) => (
  <div className="upload-help-item">
    <span className="upload-help-icon">{icon}</span>
    <span>
      <strong>{title}</strong>
      <small>{body}</small>
    </span>
  </div>
);

const ProcessingSlotBusyCard = ({
  isChecking,
  onCheckAgain,
}: {
  isChecking: boolean;
  onCheckAgain: () => void;
}) => (
  <section
    className="processing-slot-busy-card"
    aria-labelledby="processing-slot-busy-title"
  >
    <div className="processing-slot-busy-main">
      <span className="processing-slot-busy-icon" aria-hidden="true">
        <UsersRound className="processing-slot-users" />
        <Clock3 className="processing-slot-clock" />
      </span>
      <div className="processing-slot-busy-copy">
        <h3 id="processing-slot-busy-title">Processing slot is busy</h3>
        <p>
          Another user is currently processing a transcription. Please try again
          in a few minutes.
        </p>
      </div>
    </div>
    <div className="processing-slot-busy-footer">
      <p>
        <Lightbulb aria-hidden="true" />
        <span>
          Transcriptions are processed one at a time to ensure the best possible
          quality.
        </span>
      </p>
      <button
        type="button"
        className="processing-slot-check-button"
        onClick={onCheckAgain}
        disabled={isChecking}
      >
        <RotateCw aria-hidden="true" />
        {isChecking ? "Checking..." : "Check again"}
      </button>
    </div>
  </section>
);

const stemOptions: Array<{
  value: StemSelection;
  label: string;
  detail: string;
  icon: React.ReactNode;
}> = [
  {
    value: "vocals",
    label: "Vocals",
    detail: "Save the isolated vocal stem",
    icon: <Mic2 aria-hidden="true" />,
  },
  {
    value: "drums",
    label: "Drums",
    detail: "Save drums and rhythm timing",
    icon: <AudioWaveform aria-hidden="true" />,
  },
  {
    value: "bass",
    label: "Bass",
    detail: "Bass MIDI/TAB where detected",
    icon: <SlidersHorizontal aria-hidden="true" />,
  },
  {
    value: "other",
    label: "Other / Guitar / Piano / Melody",
    detail: "MVP guitar target; piano may be grouped here",
    icon: <Guitar aria-hidden="true" />,
  },
];

const StemSelector = ({
  selectedStem,
  onSelect,
}: {
  selectedStem: StemSelection | "";
  onSelect: (stem: StemSelection) => void;
}) => (
  <section className="stem-selector" aria-labelledby="stem-selector-title">
    <div className="stem-selector-heading">
      <span id="stem-selector-title">Choose one target stem</span>
      <small>Demucs default stems: vocals, drums, bass, other.</small>
    </div>
    <div
      className="stem-option-grid"
      role="radiogroup"
      aria-label="Target stem"
    >
      {stemOptions.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`stem-option ${selectedStem === option.value ? "active" : ""}`}
          role="radio"
          aria-checked={selectedStem === option.value}
          onClick={() => onSelect(option.value)}
        >
          <span className="stem-option-icon">{option.icon}</span>
          <span>
            <strong>{option.label}</strong>
            <small>{option.detail}</small>
          </span>
        </button>
      ))}
    </div>
    <p className="stem-selector-note">
      {getStemLimitationNotice(selectedStem || "other")}
    </p>
  </section>
);

export default AudioUpload;
