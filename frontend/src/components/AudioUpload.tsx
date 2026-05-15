import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import gsap from "gsap";
import {
  AudioWaveform,
  CloudUpload,
  Folder,
  Guitar,
  ShieldCheck,
  SlidersHorizontal,
  Video,
} from "lucide-react";
import audioService from "../services/audioService";
import { useAuth } from "./auth/AuthContext";

const AudioUpload: React.FC = () => {
  const { token } = useAuth();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const waveRef = useRef<HTMLDivElement | null>(null);
  const cloudRef = useRef<HTMLDivElement | null>(null);
  const dropzoneRef = useRef<HTMLDivElement | null>(null);
  const [activeTab, setActiveTab] = useState<"file" | "youtube">("file");
  const [file, setFile] = useState<File | null>(null);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(0);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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

    setIsUploading(true);
    setUploadProgress(0);
    setError(null);
    setSuccess(null);

    try {
      const response = await audioService.uploadAudioFile(file, token, undefined, (progress) => {
        setUploadProgress(Math.min(progress, 95));
      });
      setUploadProgress(100);
      setSuccess(`File uploaded successfully. Transcription ID: ${response.id}`);

      setTimeout(() => {
        navigate(`/processing/${response.id}`);
      }, 1500);
    } catch (err: any) {
      setUploadProgress(0);
      setError(err.response?.data?.detail || "Upload failed. Please try again.");
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
      const response = await audioService.extractAudioFromYouTube(youtubeUrl, token);
      setUploadProgress(100);
      setSuccess(`YouTube audio extracted successfully. Transcription ID: ${response.id}`);

      setTimeout(() => {
        navigate(`/processing/${response.id}`);
      }, 1500);
    } catch (err: any) {
      setUploadProgress(0);
      setError(err.response?.data?.detail || "Failed to extract audio from YouTube. Please try again.");
    } finally {
      setIsUploading(false);
    }
  };

  const resetForm = () => {
    setFile(null);
    setYoutubeUrl("");
    setUploadProgress(0);
    setError(null);
    setSuccess(null);
  };
  const fileUploadStatus = isUploading
    ? uploadProgress === null
      ? "Preparing audio..."
      : uploadProgress >= 95
        ? "Finishing upload..."
        : `Uploading ${Math.round(uploadProgress)}%`
    : file
      ? "Ready to upload"
      : "Upload audio";
  const fileUploadStatusDetail = file
    ? file.name
    : "We'll handle the rest";
  const fileProgressValue = isUploading
    ? uploadProgress === null
      ? 35
      : Math.min(uploadProgress, 95)
    : file
      ? 0
      : 0;

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
            <span className="upload-headline-line upload-headline-accent">transcription</span>
          </h2>
          <span className="upload-header-divider" aria-hidden="true" />
          <p>Upload a clean guitar recording or extract audio from YouTube, then send it into the analysis pipeline.</p>
        </header>

        <div className="transcription-upload-shell">
          <div className="audio-upload-tabs" role="tablist" aria-label="Upload source">
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
                  <p className="file-upload-text">or choose a file from your device</p>
                  <button
                    type="button"
                    className="browse-button"
                    onClick={() => document.getElementById("file-input")?.click()}
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
                  <p className="file-limits">Supported formats: MP3, WAV &bull; Maximum size: 100MB</p>

                  {file && (
                    <div className="selected-file">
                      <span className="file-name">{file.name}</span>
                      <span className="file-size">{(file.size / (1024 * 1024)).toFixed(2)} MB</span>
                      <button
                        type="button"
                        className="remove-file-button"
                        onClick={() => setFile(null)}
                        disabled={isUploading}
                      >
                        Remove
                      </button>
                      <button type="button" className="upload-button" onClick={handleFileUpload} disabled={isUploading}>
                        {isUploading ? "Uploading..." : "Upload audio"}
                      </button>
                    </div>
                  )}

                  <div
                    className={`upload-audio-note ${file ? "has-file" : ""} ${isUploading ? "is-uploading" : ""}`}
                    style={{
                      "--upload-progress": `${fileProgressValue}%`,
                      "--upload-progress-ratio": fileProgressValue / 100,
                    } as React.CSSProperties}
                  >
                    <AudioWaveform aria-hidden="true" />
                    <span>
                      <strong>{fileUploadStatus}</strong>
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
                      disabled={isUploading || !youtubeUrl.trim()}
                    >
                      {isUploading ? "Processing..." : "Extract audio"}
                    </button>
                  </div>
                  <p className="youtube-help">Use a public YouTube link with clear guitar audio for best extraction results.</p>
                </div>
              )}

            </div>

            <aside className="upload-help-column" aria-label="Upload guidance">
              <HelpItem icon={<SlidersHorizontal aria-hidden="true" />} title="Clean audio = better results" body="Remove background noise for higher accuracy." />
              <HelpItem icon={<Guitar aria-hidden="true" />} title="Guitar recordings work best" body="Solo guitar or minimal background instruments." />
              <HelpItem icon={<ShieldCheck aria-hidden="true" />} title="Your files are private" body="We never share your audio or your transcriptions." />
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

export default AudioUpload;
