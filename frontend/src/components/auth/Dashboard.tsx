import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import audioService, { type Transcription } from "../../services/audioService";
import { Icon } from "../Icon";
import { useAuth } from "./AuthContext";

interface Project {
  id: number;
  title: string;
  description: string;
  createdAt: string;
  audioFileName: string;
  status: "processing" | "completed" | "failed";
  duration: number;
  difficulty: "beginner" | "intermediate" | "advanced";
}

const filenameFromPath = (path?: string | null): string =>
  path?.split(/[\\/]/).pop() || "Audio source";

const getTranscriptionStatus = (transcription: Transcription): Project["status"] => {
  if (transcription.processing_error) return "failed";
  return transcription.is_processed ? "completed" : "processing";
};

const getDifficulty = (duration?: number | null): Project["difficulty"] => {
  if (!duration || duration < 180) return "beginner";
  if (duration < 360) return "intermediate";
  return "advanced";
};

const mapTranscriptionToProject = (transcription: Transcription): Project => {
  const status = getTranscriptionStatus(transcription);
  const audioFileName = transcription.youtube_url
    ? "YouTube audio"
    : filenameFromPath(transcription.audio_file_path);

  return {
    id: transcription.id,
    title: transcription.title || `Transcription ${transcription.id}`,
    description:
      status === "failed"
        ? transcription.processing_error || "Processing failed"
        : status === "completed"
          ? "Score, tab, and exports are ready"
          : "Analysis is running in the background",
    createdAt: transcription.created_at || new Date().toISOString(),
    audioFileName,
    status,
    duration: transcription.duration || 0,
    difficulty: getDifficulty(transcription.duration),
  };
};

const formatDuration = (duration: number): string => {
  const wholeSeconds = Math.max(0, Math.floor(duration));
  const minutes = Math.floor(wholeSeconds / 60);
  const seconds = wholeSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
};

const parseApiDate = (value: string): Date => {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
};

const formatCreatedDate = (value: string): string =>
  parseApiDate(value).toLocaleDateString();

const formatCreatedDateTime = (value: string): string =>
  parseApiDate(value).toLocaleString();

const getStatusGradient = (status: Project["status"]) => {
  switch (status) {
    case "completed":
      return "linear-gradient(135deg, #42755f, #244c69)";
    case "processing":
      return "linear-gradient(135deg, #bf8d31, #a8481d)";
    case "failed":
      return "linear-gradient(135deg, #aa3f34, #722f16)";
    default:
      return "linear-gradient(135deg, #4e4a44, #171513)";
  }
};

const getDifficultyColor = (difficulty: Project["difficulty"]) => {
  switch (difficulty) {
    case "beginner":
      return "#42755f";
    case "intermediate":
      return "#bf8d31";
    case "advanced":
      return "#aa3f34";
    default:
      return "#4e4a44";
  }
};

const Dashboard: React.FC = () => {
  const { user, token } = useAuth();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  const handleNewTranscription = () => {
    navigate("/upload");
  };

  const getProjectRoute = (project: Project): string =>
    project.status === "completed"
      ? `/transcription/${project.id}`
      : `/processing/${project.id}`;

  useEffect(() => {
    let isMounted = true;
    let refreshTimer: ReturnType<typeof window.setInterval> | undefined;

    const hasProcessingProject = (projectList: Project[]) =>
      projectList.some((project) => project.status === "processing");

    const stopAutoRefresh = () => {
      if (refreshTimer) {
        window.clearInterval(refreshTimer);
        refreshTimer = undefined;
      }
    };

    const loadProjects = async (showLoading: boolean) => {
      if (!token) {
        if (isMounted) {
          setProjects([]);
          setLoading(false);
        }
        return [];
      }

      try {
        if (showLoading && isMounted) setLoading(true);
        if (isMounted) setLoadError(null);

        const transcriptions = await audioService.listTranscriptions(token);
        const nextProjects = transcriptions.map(mapTranscriptionToProject);

        if (isMounted) {
          setProjects(nextProjects);
          setLoading(false);
        }

        return nextProjects;
      } catch (error: any) {
        if (isMounted) {
          setLoadError(error.response?.data?.detail || "Failed to load transcriptions");
          if (showLoading) setProjects([]);
          setLoading(false);
        }
        return null;
      }
    };

    const startAutoRefresh = async () => {
      const initialProjects = await loadProjects(true);
      if (!initialProjects || !hasProcessingProject(initialProjects)) return;

      refreshTimer = window.setInterval(async () => {
        const latestProjects = await loadProjects(false);
        if (latestProjects && !hasProcessingProject(latestProjects)) {
          stopAutoRefresh();
        }
      }, 5000);
    };

    startAutoRefresh();

    return () => {
      isMounted = false;
      stopAutoRefresh();
    };
  }, [token]);

  if (!user) {
    navigate("/login");
    return null;
  }

  const completedCount = projects.filter((project) => project.status === "completed").length;
  const processingCount = projects.filter((project) => project.status === "processing").length;
  const totalMinutes = Math.floor(projects.reduce((sum, project) => sum + project.duration, 0) / 60);

  return (
    <div className="dashboard-page">
      <div className="dashboard-content">
        <header className="dashboard-header">
          <div className="dashboard-header-content">
            <h1 className="dashboard-title">MusicSheet Studio</h1>
            <p className="dashboard-subtitle">
              Welcome back, {user.username}. Turn rough audio into readable guitar scores, clean tabs, and exportable practice files.
            </p>
          </div>
          <div className="dashboard-header-actions">
            <button
              onClick={() => setViewMode(viewMode === "grid" ? "list" : "grid")}
              className={`view-mode-button icon-button ${viewMode === "list" ? "active" : ""}`}
              aria-label={viewMode === "grid" ? "Switch to list view" : "Switch to grid view"}
              title={viewMode === "grid" ? "List view" : "Grid view"}
            >
              <Icon name={viewMode === "grid" ? "list" : "grid"} />
            </button>
            <button onClick={handleNewTranscription} className="new-transcription-button">
              <Icon name="plus" />
              <span>New transcription</span>
            </button>
          </div>
        </header>

        <main className="dashboard-main">
          <div className="dashboard-stats">
            <div className="stat-card">
              <div className="stat-content">
                <h3 className="stat-value">{projects.length}</h3>
                <p className="stat-label">Total projects</p>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-content">
                <h3 className="stat-value">{completedCount}</h3>
                <p className="stat-label">Completed</p>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-content">
                <h3 className="stat-value">{processingCount}</h3>
                <p className="stat-label">Processing</p>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-content">
                <h3 className="stat-value">{totalMinutes}m</h3>
                <p className="stat-label">Analyzed audio</p>
              </div>
            </div>
          </div>

          <section className="projects-section">
            <h2 className="section-title">Your music projects</h2>
            {loadError && <div className="alert alert-error">{loadError}</div>}

            {loading ? (
              <div className="loading-state">
                <div className="loading-spinner"></div>
                <p className="loading-text">Loading your transcription library...</p>
              </div>
            ) : projects.length === 0 ? (
              <div className="empty-state">
                <h3 className="empty-state-title">Your first score is waiting</h3>
                <p className="empty-state-description">
                  Upload an MP3, WAV, or YouTube link and let the studio generate guitar notation from it.
                </p>
                <button onClick={handleNewTranscription} className="primary-action-button">
                  Start first transcription
                </button>
              </div>
            ) : (
              <div className={`projects-container ${viewMode}`}>
                {viewMode === "grid" ? (
                  <div className="projects-grid">
                    {projects.map((project) => (
                      <article
                        key={project.id}
                        className={`project-card project-card-${project.status}`}
                        onDoubleClick={() => navigate(getProjectRoute(project))}
                      >
                        <div className="project-card-header">
                          <h3 className="project-title">{project.title}</h3>
                          <div className="project-status-badge" style={{ background: getStatusGradient(project.status) }}>
                            {project.status}
                          </div>
                        </div>

                        <div className="project-body">
                          <p className="project-description">{project.description}</p>

                          <div className="project-meta">
                            <div className="meta-item">
                              <span className="meta-label">Source</span>
                              <span className="meta-value">{project.audioFileName}</span>
                            </div>
                            <div className="meta-item">
                              <span className="meta-label">Duration</span>
                              <span className="meta-value">{formatDuration(project.duration)}</span>
                            </div>
                            <div className="meta-item">
                              <span className="meta-label">Created</span>
                              <span className="meta-value">{formatCreatedDate(project.createdAt)}</span>
                            </div>
                          </div>

                          <div className="project-tags">
                            <span
                              className="difficulty-tag"
                              style={{
                                color: getDifficultyColor(project.difficulty),
                              }}
                            >
                              <Icon name="gauge" />
                              {project.difficulty}
                            </span>
                            {project.status === "completed" && (
                              <span className="quality-badge">
                                <Icon name="check" />
                                export ready
                              </span>
                            )}
                          </div>
                        </div>

                        <div className="project-actions">
                          <button onClick={() => navigate(getProjectRoute(project))} className="action-button view-button">
                            <Icon name="eye" />
                            <span>View</span>
                          </button>
                          {project.status === "completed" && (
                            <button onClick={() => navigate(getProjectRoute(project))} className="action-button export-button">
                              <Icon name="download" />
                              <span>Exports</span>
                            </button>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="projects-list">
                    {projects.map((project) => (
                      <article key={project.id} className={`project-list-item project-list-item-${project.status}`}>
                        <div className="project-list-content">
                          <div className="project-list-header">
                            <h3 className="project-list-title">{project.title}</h3>
                            <div className="project-list-status" style={{ background: getStatusGradient(project.status) }}>
                              {project.status}
                            </div>
                          </div>

                          <div className="project-list-body">
                            <p className="project-list-description">{project.description}</p>

                            <div className="project-list-info">
                              <div className="info-row">
                                <span className="info-label">File</span>
                                <span className="info-value">{project.audioFileName}</span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Duration</span>
                                <span className="info-value">{formatDuration(project.duration)}</span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Difficulty</span>
                                <span className="info-value" style={{ color: getDifficultyColor(project.difficulty) }}>
                                  {project.difficulty}
                                </span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Created</span>
                                <span className="info-value">{formatCreatedDateTime(project.createdAt)}</span>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="project-list-actions">
                          <button onClick={() => navigate(getProjectRoute(project))} className="action-button list-action-button">
                            <Icon name="eye" />
                            <span>View</span>
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="quick-actions-section">
            <h2 className="section-title">Quick actions</h2>
            <div className="quick-actions-grid">
              <button onClick={handleNewTranscription} className="quick-action-button">
                <div className="quick-action-content">
                  <h3>Upload audio</h3>
                  <p>MP3, WAV, or YouTube URL</p>
                </div>
              </button>

              <button onClick={() => alert("Recording feature coming soon.")} className="quick-action-button">
                <div className="quick-action-content">
                  <h3>Record audio</h3>
                  <p>Capture directly from mic</p>
                </div>
              </button>

              <button onClick={() => alert("Batch processing coming soon.")} className="quick-action-button">
                <div className="quick-action-content">
                  <h3>Batch process</h3>
                  <p>Multiple files at once</p>
                </div>
              </button>

              <button onClick={() => alert("Template library coming soon.")} className="quick-action-button">
                <div className="quick-action-content">
                  <h3>Templates</h3>
                  <p>Start with arrangement presets</p>
                </div>
              </button>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
};

export default Dashboard;
