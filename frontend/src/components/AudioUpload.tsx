import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import audioService from "../services/audioService";
import { useAuth } from "./auth/AuthContext";

const AudioUpload: React.FC = () => {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<"file" | "youtube">("file");
  const [file, setFile] = useState<File | null>(null);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(0);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const navigate = useNavigate();

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
      const response = await audioService.uploadAudioFile(file, token, undefined, setUploadProgress);
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

  return (
    <div className="audio-upload-container">
      <div className="audio-upload-header">
        <h2>Start a transcription</h2>
        <p>Upload a clean guitar recording or extract audio from YouTube, then send it into the analysis pipeline.</p>
      </div>

      <div className="audio-upload-tabs">
        <button
          className={`tab-button ${activeTab === "file" ? "active" : ""}`}
          onClick={() => setActiveTab("file")}
        >
          File upload
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
            <p>Drop your audio file here</p>
            <p className="file-upload-text">or choose a local file</p>
            <button
              className="browse-button"
              onClick={() => document.getElementById("file-input")?.click()}
            >
              Browse files
            </button>
            <input
              type="file"
              id="file-input"
              accept=".mp3,.wav"
              style={{ display: "none" }}
              onChange={handleFileChange}
            />
            <p className="file-limits">Supported formats: MP3, WAV. Maximum size: 100MB.</p>
          </div>

          {file && (
            <div className="selected-file">
              <span className="file-name">{file.name}</span>
              <span className="file-size">{(file.size / (1024 * 1024)).toFixed(2)} MB</span>
              <button className="remove-file-button" onClick={() => setFile(null)}>
                Remove
              </button>
            </div>
          )}

          <button className="upload-button" onClick={handleFileUpload} disabled={isUploading || !file}>
            {isUploading ? "Uploading..." : "Upload audio"}
          </button>
        </div>
      ) : (
        <div className="youtube-upload-section">
          <div className="youtube-input-group">
            <input
              type="text"
              placeholder="Paste a YouTube URL"
              value={youtubeUrl}
              onChange={(e) => setYoutubeUrl(e.target.value)}
              disabled={isUploading}
            />
            <button
              className="youtube-button"
              onClick={handleYoutubeSubmit}
              disabled={isUploading || !youtubeUrl.trim()}
            >
              {isUploading ? "Processing..." : "Extract audio"}
            </button>
          </div>
          <p className="youtube-help">Use public YouTube links for source extraction and transcription.</p>
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
            Close
          </button>
        </div>
      )}

      {isUploading && uploadProgress !== 100 && (
        <div className="upload-progress">
          <div className="progress-bar">
            <div
              className={`progress-fill ${uploadProgress === null ? "indeterminate" : ""}`}
              style={{ width: uploadProgress === null ? undefined : `${uploadProgress}%` }}
            ></div>
          </div>
          <p className="progress-text">
            {uploadProgress === null ? "Preparing audio..." : `${uploadProgress}%`}
          </p>
        </div>
      )}
    </div>
  );
};

export default AudioUpload;
