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

const isNonBlockingProcessingWarning = (error?: string | null): boolean =>
  Boolean(error?.startsWith("Source separation unavailable; processed the full mix instead."));

const getTranscriptionStatus = (transcription: Transcription): Project["status"] => {
  if (transcription.processing_error && !isNonBlockingProcessingWarning(transcription.processing_error)) {
    return "failed";
  }
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
          ? transcription.processing_error && isNonBlockingProcessingWarning(transcription.processing_error)
            ? "Score and exports are ready from the full mix"
            : "Score, tab, and exports are ready"
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
  const cachedTranscriptions = audioService.getCachedTranscriptions(token);
  const [projects, setProjects] = useState<Project[]>(
    () => cachedTranscriptions?.map(mapTranscriptionToProject) ?? [],
  );
  const [loading, setLoading] = useState(!cachedTranscriptions);
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
      const cachedProjects = audioService
        .getCachedTranscriptions(token)
        ?.map(mapTranscriptionToProject);

      if (cachedProjects && isMounted) {
        setProjects(cachedProjects);
        setLoading(false);
      }

      const initialProjects = await loadProjects(!cachedProjects);
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
  const featuredProject = projects[0];
  const statCards = [
    { label: "Total projects", value: projects.length, icon: "folder" as const, tone: "amber" },
    { label: "Completed", value: completedCount, icon: "check" as const, tone: "green" },
    { label: "Processing", value: processingCount, icon: "clock" as const, tone: "gold" },
    { label: "Analyzed audio", value: `${totalMinutes}m`, icon: "waveform" as const, tone: "blue" },
  ];
  const quickActions = [
    {
      title: "Upload audio",
      description: "MP3, WAV, or YouTube URL",
      icon: "upload" as const,
      onClick: handleNewTranscription,
    },
    {
      title: "Record audio",
      description: "Capture directly from mic",
      icon: "microphone" as const,
      onClick: () => alert("Recording feature coming soon."),
    },
    {
      title: "Batch process",
      description: "Multiple files at once",
      icon: "layers" as const,
      onClick: () => alert("Batch processing coming soon."),
    },
    {
      title: "Templates",
      description: "Start with arrangement presets",
      icon: "file" as const,
      onClick: () => alert("Template library coming soon."),
    },
  ];
  const ProjectCover = ({ title }: { title: string }) => (
    <div className="project-cover" aria-label={`${title} audio artwork`}>
      <span className="project-cover-orbit" aria-hidden="true" />
      <span className="project-cover-play" aria-hidden="true">
        <Icon name="arrow" />
      </span>
    </div>
  );

  return (
    <div className="dashboard-page">
      <div className="dashboard-content">
        <header className="dashboard-header cinematic-dashboard-hero">
          <div className="dashboard-hero-art" aria-hidden="true">
            <span className="dashboard-hero-glow" />
            <span className="dashboard-hero-wave wave-one" />
            <span className="dashboard-hero-wave wave-two" />
            <span className="dashboard-hero-wave wave-three" />
            <span className="dashboard-guitar-plate" />
            <span className="dashboard-guitar-neck" />
            <span className="dashboard-guitar-soundhole" />
            <span className="dashboard-guitar-strings" />
            <span className="dashboard-hero-sweep" />
          </div>
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
            {statCards.map((stat) => (
              <div className={`stat-card stat-card-${stat.tone}`} key={stat.label}>
                <Icon name={stat.icon} />
                <div className="stat-content">
                  <h3 className="stat-value">{stat.value}</h3>
                  <p className="stat-label">{stat.label}</p>
                </div>
                <span className="stat-sparkline" aria-hidden="true" />
              </div>
            ))}
          </div>

          <section className="projects-section">
            <h2 className="section-title">Recent project</h2>
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
            ) : featuredProject && viewMode === "grid" ? (
              <article
                className={`project-card featured-project-card project-card-${featuredProject.status}`}
                onDoubleClick={() => navigate(getProjectRoute(featuredProject))}
              >
                <ProjectCover title={featuredProject.title} />
                <div className="project-body">
                  <div className="project-card-header">
                    <h3 className="project-title">{featuredProject.title}</h3>
                    <div className="project-status-badge" style={{ background: getStatusGradient(featuredProject.status) }}>
                      {featuredProject.status}
                    </div>
                    <button type="button" className="project-more-button" aria-label="More project actions">
                      <Icon name="more" />
                    </button>
                  </div>

                  <p className="project-description">{featuredProject.description}</p>

                  <div className="project-meta">
                    <div className="meta-item">
                      <span className="meta-label">Source</span>
                      <span className="meta-value">{featuredProject.audioFileName}</span>
                    </div>
                    <div className="meta-item">
                      <span className="meta-label">Duration</span>
                      <span className="meta-value">{formatDuration(featuredProject.duration)}</span>
                    </div>
                    <div className="meta-item">
                      <span className="meta-label">Created</span>
                      <span className="meta-value">{formatCreatedDate(featuredProject.createdAt)}</span>
                    </div>
                  </div>

                  <div className="project-tags">
                    <span
                      className="difficulty-tag"
                      style={{
                        color: getDifficultyColor(featuredProject.difficulty),
                      }}
                    >
                      <Icon name="gauge" />
                      {featuredProject.difficulty}
                    </span>
                    {featuredProject.status === "completed" && (
                      <span className="quality-badge">
                        <Icon name="check" />
                        export ready
                      </span>
                    )}
                  </div>
                </div>

                <div className="project-actions">
                  <button onClick={() => navigate(getProjectRoute(featuredProject))} className="action-button view-button">
                    <Icon name="eye" />
                    <span>View</span>
                  </button>
                  <button onClick={() => navigate(getProjectRoute(featuredProject))} className="action-button export-button">
                    <Icon name="download" />
                    <span>Exports</span>
                  </button>
                </div>
              </article>
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
                        <ProjectCover title={project.title} />
                        <div className="project-body">
                          <div className="project-card-header">
                            <h3 className="project-title">{project.title}</h3>
                            <div className="project-status-badge" style={{ background: getStatusGradient(project.status) }}>
                              {project.status}
                            </div>
                          </div>
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
                        <ProjectCover title={project.title} />
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

          {projects.length > 1 && viewMode === "grid" && (
            <section className="projects-section dashboard-library-section">
              <h2 className="section-title">Project library</h2>
              <div className="projects-container grid">
                <div className="projects-grid">
                  {projects.slice(1).map((project) => (
                    <article
                      key={project.id}
                      className={`project-card project-card-${project.status}`}
                      onDoubleClick={() => navigate(getProjectRoute(project))}
                    >
                      <ProjectCover title={project.title} />
                      <div className="project-body">
                        <div className="project-card-header">
                          <h3 className="project-title">{project.title}</h3>
                          <div className="project-status-badge" style={{ background: getStatusGradient(project.status) }}>
                            {project.status}
                          </div>
                        </div>
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
              </div>
            </section>
          )}

          <section className="quick-actions-section">
            <div className="quick-actions-grid">
              {quickActions.map((action) => (
                <button onClick={action.onClick} className="quick-action-button" key={action.title}>
                  <span className="quick-action-icon">
                    <Icon name={action.icon} />
                  </span>
                  <div className="quick-action-content">
                    <h3>{action.title}</h3>
                    <p>{action.description}</p>
                  </div>
                  <span className="quick-action-arrow">
                    <Icon name="arrow" />
                  </span>
                </button>
              ))}
            </div>
          </section>
        </main>
      </div>
    </div>
  );
};

export default Dashboard;
