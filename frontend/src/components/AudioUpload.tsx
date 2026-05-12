import React, { useState } from "react";
import audioService from "../services/audioService";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";

const AudioUpload: React.FC = () => {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<"file" | "youtube">("file");
  const [file, setFile] = useState<File | null>(null);
  const [youtubeUrl, setYoutubeUrl] = useState<string>("");
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const navigate = useNavigate();

  // Handle file selection
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setError(null);
      setSuccess(null);
    }
  };

  // Handle drag over
  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.add("dragover");
  };

  // Handle drag leave
  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove("dragover");
  };

  // Handle drop
  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove("dragover");

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      // Validate file type
      const fileExtension = `.${droppedFile.name.split(".").pop().toLowerCase()}`;
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

  // Handle file upload
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
    setError(null);
    setSuccess(null);

    let progressInterval: NodeJS.Timeout | null = null;

    try {
      // Simulate upload progress (in a real app, you'd use axios progress events)
      progressInterval = setInterval(() => {
        setUploadProgress((prev) => Math.min(prev + 10, 90));
      }, 100);

      const response = await audioService.uploadAudioFile(file, token);

      if (progressInterval) clearInterval(progressInterval);
      setUploadProgress(100);

      setSuccess(
        `File uploaded successfully! Transcription ID: ${response.id}`,
      );

      // Navigate to transcription result page after a short delay
      setTimeout(() => {
        navigate(`/transcription/${response.id}`);
      }, 1500);
    } catch (err: any) {
      if (progressInterval) clearInterval(progressInterval);
      setUploadProgress(0);
      setError(
        err.response?.data?.detail || "Upload failed. Please try again.",
      );
    } finally {
      setIsUploading(false);
    }
  };

  // Handle YouTube URL submission
  const handleYoutubeSubmit = async () => {
    if (!youtubeUrl.trim()) {
      setError("Please enter a YouTube URL");
      return;
    }

    if (!token) {
      setError("Authentication error. Please log in again.");
      return;
    }

    // Basic YouTube URL validation
    const youtubeRegex = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+/;
    if (!youtubeRegex.test(youtubeUrl)) {
      setError("Please enter a valid YouTube URL");
      return;
    }

    setIsUploading(true);
    setError(null);
    setSuccess(null);

    let progressInterval: NodeJS.Timeout | null = null;

    try {
      // Simulate upload progress
      progressInterval = setInterval(() => {
        setUploadProgress((prev) => Math.min(prev + 10, 90));
      }, 100);

      const response = await audioService.extractAudioFromYouTube(
        youtubeUrl,
        token,
      );

      if (progressInterval) clearInterval(progressInterval);
      setUploadProgress(100);

      setSuccess(
        `YouTube audio extracted successfully! Transcription ID: ${response.id}`,
      );

      // Navigate to transcription result page after a short delay
      setTimeout(() => {
        navigate(`/transcription/${response.id}`);
      }, 1500);
    } catch (err: any) {
      if (progressInterval) clearInterval(progressInterval);
      setUploadProgress(0);
      setError(
        err.response?.data?.detail ||
          "Failed to extract audio from YouTube. Please try again.",
      );
    } finally {
      setIsUploading(false);
    }
  };

  // Reset form
  const resetForm = () => {
    setFile(null);
    setYoutubeUrl("");
    setUploadProgress(0);
    setError(null);
    setSuccess(null);
  };

  return (
    <div className="audio-upload-container">
      <div className="audio-upload-header">
        <h2>Upload Audio for Transcription</h2>
        <p>Convert your audio files or YouTube videos into guitar tabs</p>
      </div>

      <div className="audio-upload-tabs">
        <button
          className={`tab-button ${activeTab === "file" ? "active" : ""}`}
          onClick={() => setActiveTab("file")}
        >
          File Upload
        </button>
        <button
          className={`tab-button ${activeTab === "youtube" ? "active" : ""}`}
          onClick={() => setActiveTab("youtube")}
        >
          YouTube URL
        </button>
      </div>

      {activeTab === "file" ? (
        <div className="file-upload-section">
          <div
            className="file-upload-area"
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div className="file-upload-icon">📁</div>
            <p>Drag & drop your audio file here</p>
            <p className="file-upload-text">or</p>
            <button
              className="browse-button"
              onClick={() => document.getElementById("file-input")?.click()}
            >
              Browse Files
            </button>
            <input
              type="file"
              id="file-input"
              accept=".mp3,.wav"
              style={{ display: "none" }}
              onChange={handleFileChange}
            />
            <p className="file-limits">
              Supported formats: MP3, WAV • Maximum size: 100MB
            </p>
          </div>

          {file && (
            <div className="selected-file">
              <span className="file-name">📄 {file.name}</span>
              <span className="file-size">
                {(file.size / (1024 * 1024)).toFixed(2)} MB
              </span>
              <button
                className="remove-file-button"
                onClick={() => setFile(null)}
              >
                Remove
              </button>
            </div>
          )}

          <button
            className="upload-button"
            onClick={handleFileUpload}
            disabled={isUploading || !file}
          >
            {isUploading ? (
              <>
                <span className="uploading-icon">⏳</span>
                <span>Uploading...</span>
              </>
            ) : (
              <>
                <span className="upload-icon">🚀</span>
                <span>Upload Audio</span>
              </>
            )}
          </button>
        </div>
      ) : (
        <div className="youtube-upload-section">
          <div className="youtube-input-group">
            <input
              type="text"
              placeholder="Enter YouTube URL..."
              value={youtubeUrl}
              onChange={(e) => setYoutubeUrl(e.target.value)}
              disabled={isUploading}
            />
            <button
              className="youtube-button"
              onClick={handleYoutubeSubmit}
              disabled={isUploading || !youtubeUrl.trim()}
            >
              {isUploading ? (
                <>
                  <span className="uploading-icon">⏳</span>
                  <span>Processing...</span>
                </>
              ) : (
                <>
                  <span className="youtube-icon">🎵</span>
                  <span>Extract Audio</span>
                </>
              )}
            </button>
          </div>
          <p className="youtube-help">
            Paste any YouTube URL to extract audio for transcription
          </p>
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      {success && (
        <div className="alert alert-success">
          {success}
          <button
            className="close-alert"
            onClick={() => {
              setSuccess(null);
              resetForm();
            }}
          >
            ×
          </button>
        </div>
      )}

      {isUploading && uploadProgress > 0 && uploadProgress < 100 && (
        <div className="upload-progress">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${uploadProgress}%` }}
            ></div>
          </div>
          <p className="progress-text">{uploadProgress}%</p>
        </div>
      )}
    </div>
  );
};

export default AudioUpload;
