import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import audioService, { type Transcription } from "../../services/audioService";
import {
  buildTranscriptionMetadata,
  type TranscriptionMetadata,
} from "../../utils/transcriptionMetadata";
import { Icon } from "../Icon";
import { useAuth } from "./AuthContext";

interface Project {
  id: number;
  title: string;
  description: string;
  createdAt: string;
  audioFileName: string;
  status:
    | "pending"
    | "queued"
    | "processing"
    | "stem_ready"
    | "completed"
    | "warning"
    | "failed";
  duration: number;
  difficulty: "beginner" | "intermediate" | "advanced";
  processingError?: string | null;
  isDemo?: boolean;
  metadata: TranscriptionMetadata;
  playbackAudioUrl?: string | null;
}

const filenameFromPath = (path?: string | null): string =>
  path?.split(/[\\/]/).pop() || "Audio source";

const isNonBlockingProcessingWarning = (error?: string | null): boolean =>
  Boolean(
    error?.startsWith(
      "Source separation unavailable; processed the full mix instead.",
    ),
  );

const getTranscriptionStatus = (
  transcription: Transcription,
): Project["status"] => {
  if (
    transcription.processing_status === "pending" ||
    transcription.processing_status === "queued" ||
    transcription.processing_status === "processing" ||
    transcription.processing_status === "stem_ready" ||
    transcription.processing_status === "completed" ||
    transcription.processing_status === "completed_with_warning" ||
    transcription.processing_status === "failed"
  ) {
    if (transcription.processing_status === "completed_with_warning") {
      return "warning";
    }
    return transcription.processing_status;
  }
  if (
    transcription.processing_error &&
    !isNonBlockingProcessingWarning(transcription.processing_error)
  ) {
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
  const metadata = buildTranscriptionMetadata(transcription);
  const selectedStem = (transcription.selected_stem || "other").toLowerCase();
  const stemReadyDescription =
    selectedStem === "drums"
      ? "Drum stem is ready. Listen first, then generate rhythm if the stem sounds useful."
      : selectedStem === "vocals"
        ? "Vocal stem is ready. Listen first, then generate lyrics when you want a timestamped transcription."
        : "Stem is ready. Listen first, then generate tabs if the stem sounds useful.";
  const audioFileName = transcription.youtube_url
    ? "YouTube audio"
    : transcription.is_demo
      ? "Bundled demo stem"
      : filenameFromPath(transcription.audio_file_path);

  return {
    id: transcription.id,
    title: transcription.title || `Transcription ${transcription.id}`,
    description: transcription.is_demo
      ? "Try the demo transcription with playable stem audio, TAB, and notation."
      : status === "failed"
        ? transcription.processing_error || "Processing failed"
        : status === "warning"
          ? transcription.warning_message || metadata.description
          : status === "stem_ready"
            ? stemReadyDescription
            : status === "queued"
              ? "Queued for Modal processing"
              : status === "pending"
                ? "Waiting for the selected-stem job to start"
                : status === "completed"
                  ? transcription.processing_error &&
                    isNonBlockingProcessingWarning(
                      transcription.processing_error,
                    )
                    ? "Score and exports are ready from the full mix"
                    : metadata.description
                  : "Analysis is running in the background",
    createdAt: transcription.created_at || new Date().toISOString(),
    audioFileName,
    status,
    duration: metadata.durationSeconds || transcription.duration || 0,
    difficulty: getDifficulty(
      metadata.durationSeconds || transcription.duration,
    ),
    processingError: transcription.processing_error,
    isDemo: Boolean(transcription.is_demo),
    metadata,
    playbackAudioUrl: audioService.resolvePlayableAudioUrl(
      transcription.separated_audio_url,
    ),
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
    case "stem_ready":
      return "linear-gradient(135deg, #2c7c7c, #244c69)";
    case "warning":
      return "linear-gradient(135deg, #bf8d31, #7a6331)";
    case "queued":
    case "pending":
      return "linear-gradient(135deg, #7a6331, #5a4321)";
    case "processing":
      return "linear-gradient(135deg, #bf8d31, #a8481d)";
    case "failed":
      return "linear-gradient(135deg, #aa3f34, #722f16)";
    default:
      return "linear-gradient(135deg, #4e4a44, #171513)";
  }
};

const getStatusDisplay = (status: Project["status"]): string =>
  status === "warning" || status === "stem_ready" ? "Stem Ready" : status;

type ToastState = {
  tone: "success" | "error";
  message: string;
} | null;

type ProjectAction = "open" | "source" | "delete" | "error";

type ProjectActionMenuItem = {
  action: ProjectAction;
  label: string;
  icon: React.ComponentProps<typeof Icon>["name"];
  dangerous?: boolean;
};

const getProjectActionMenuItems = (
  project: Project,
): ProjectActionMenuItem[] => {
  const items: ProjectActionMenuItem[] = [];

  if (
    project.status === "completed" ||
    project.status === "warning" ||
    project.status === "stem_ready"
  ) {
    items.push({
      action: "source",
      label: project.playbackAudioUrl ? "Open stem audio" : "Open source audio",
      icon: "music",
    });
  }

  if (project.status === "processing") {
    items.push({ action: "open", label: "View progress", icon: "eye" });
  }

  if (project.status === "queued" || project.status === "pending") {
    items.push({ action: "open", label: "View queue status", icon: "clock" });
  }

  if (project.status === "failed") {
    items.push({
      action: "error",
      label: "View processing error",
      icon: "alert",
    });
  }

  if (!project.isDemo) {
    items.push({
      action: "delete",
      label: "Delete project",
      icon: "trash",
      dangerous: true,
    });
  }

  return items;
};

interface ProjectActionMenuProps {
  project: Project;
  isOpen: boolean;
  onToggle: () => void;
  onAction: (project: Project, action: ProjectAction) => void;
}

const ProjectActionMenu: React.FC<ProjectActionMenuProps> = ({
  project,
  isOpen,
  onToggle,
  onAction,
}) => (
  <div className="project-menu-shell">
    <button
      type="button"
      className={`project-more-button ${isOpen ? "active" : ""}`}
      aria-label={`${project.title} actions`}
      aria-haspopup="menu"
      aria-expanded={isOpen}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && isOpen) {
          event.stopPropagation();
          onToggle();
        }
      }}
    >
      <Icon name="more" />
    </button>

    {isOpen && (
      <div className="project-action-menu" role="menu">
        {getProjectActionMenuItems(project).map((item) => (
          <button
            key={item.action}
            type="button"
            role="menuitem"
            className={`project-action-menu-item ${item.dangerous ? "danger" : ""}`}
            onClick={(event) => {
              event.stopPropagation();
              onAction(project, item.action);
            }}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    )}
  </div>
);

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
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [openMenuProjectId, setOpenMenuProjectId] = useState<number | null>(
    null,
  );
  const [deleteCandidate, setDeleteCandidate] = useState<Project | null>(null);
  const [errorCandidate, setErrorCandidate] = useState<Project | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);
  const dashboardRef = useRef<HTMLDivElement | null>(null);
  const toastTimerRef = useRef<number | undefined>(undefined);

  const handleNewTranscription = () => {
    navigate("/upload");
  };

  const getProjectRoute = (project: Project): string =>
    project.status === "completed" || project.status === "stem_ready"
      ? `/transcription/${project.id}`
      : project.status === "warning"
        ? `/transcription/${project.id}`
        : `/processing/${project.id}`;

  const showToast = useCallback((nextToast: ToastState) => {
    if (toastTimerRef.current) {
      window.clearTimeout(toastTimerRef.current);
      toastTimerRef.current = undefined;
    }

    setToast(nextToast);
    if (nextToast) {
      toastTimerRef.current = window.setTimeout(() => {
        setToast(null);
        toastTimerRef.current = undefined;
      }, 3600);
    }
  }, []);

  const handleProjectAction = async (
    project: Project,
    action: ProjectAction,
  ) => {
    setOpenMenuProjectId(null);

    if (action === "open") {
      navigate(getProjectRoute(project));
      return;
    }

    if (action === "error") {
      setErrorCandidate(project);
      return;
    }

    if (action === "delete") {
      if (project.isDemo) {
        showToast({
          tone: "error",
          message: "Demo transcriptions are shared examples.",
        });
        return;
      }
      setDeleteCandidate(project);
      return;
    }

    if (action === "source") {
      if (!token) return;
      try {
        if (project.playbackAudioUrl) {
          window.open(project.playbackAudioUrl, "_blank", "noopener,noreferrer");
          return;
        }
        const blob = await audioService.getSourceAudio(project.id, token);
        const sourceUrl = URL.createObjectURL(blob);
        window.open(sourceUrl, "_blank", "noopener,noreferrer");
        window.setTimeout(() => URL.revokeObjectURL(sourceUrl), 60000);
      } catch (error: any) {
        showToast({
          tone: "error",
          message:
            error.response?.data?.detail || "Source audio could not be opened.",
        });
      }
    }
  };

  const confirmDeleteProject = async () => {
    if (!deleteCandidate || !token) return;
    setIsDeleting(true);
    try {
      await audioService.deleteTranscription(deleteCandidate.id, token);
      setProjects((currentProjects) =>
        currentProjects.filter((project) => project.id !== deleteCandidate.id),
      );
      setDeleteCandidate(null);
      showToast({ tone: "success", message: "Transcription deleted." });
    } catch (error: any) {
      showToast({
        tone: "error",
        message:
          error.response?.data?.detail || "Could not delete transcription.",
      });
    } finally {
      setIsDeleting(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    let refreshTimer: number | undefined;

    const hasProcessingProject = (projectList: Project[]) =>
      projectList.some(
        (project) =>
          project.status === "pending" ||
          project.status === "queued" ||
          project.status === "processing",
      );

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

        const transcriptions = await audioService.listTranscriptions(token);
        const nextProjects = transcriptions.map(mapTranscriptionToProject);

        if (isMounted) {
          setProjects(nextProjects);
          setLoading(false);
        }

        return nextProjects;
      } catch (error: any) {
        if (isMounted) {
          showToast({
            tone: "error",
            message:
              error.response?.data?.detail || "Failed to load transcriptions",
          });
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
  }, [showToast, token]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) {
        window.clearTimeout(toastTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!dashboardRef.current?.contains(event.target as Node)) {
        setOpenMenuProjectId(null);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenMenuProjectId(null);
        setDeleteCandidate(null);
        setErrorCandidate(null);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  if (!user) {
    navigate("/login");
    return null;
  }

  const completedCount = projects.filter(
    (project) =>
      project.status === "completed" ||
      project.status === "warning" ||
      project.status === "stem_ready",
  ).length;
  const processingCount = projects.filter(
    (project) =>
      project.status === "pending" ||
      project.status === "queued" ||
      project.status === "processing",
  ).length;
  const totalMinutes = Math.floor(
    projects.reduce((sum, project) => sum + project.duration, 0) / 60,
  );
  const featuredProject = projects[0];
  const sectionTitle = featuredProject?.isDemo
    ? "Try the demo transcription"
    : "Recent project";
  const statCards = [
    {
      label: "Total projects",
      value: projects.length,
      icon: "folder" as const,
      tone: "amber",
    },
    {
      label: "Completed",
      value: completedCount,
      icon: "check" as const,
      tone: "green",
    },
    {
      label: "Processing",
      value: processingCount,
      icon: "clock" as const,
      tone: "gold",
    },
    {
      label: "Analyzed audio",
      value: `${totalMinutes}m`,
      icon: "waveform" as const,
      tone: "blue",
    },
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
  const ProjectCover = ({
    title,
    tone,
  }: {
    title: string;
    tone: TranscriptionMetadata["tone"];
  }) => (
    <div
      className={`project-cover project-cover-${tone}`}
      aria-label={`${title} audio artwork`}
    >
      <span className="project-cover-orbit" aria-hidden="true" />
      <span className="project-cover-play" aria-hidden="true">
        <Icon name="arrow" />
      </span>
    </div>
  );

  const CapabilityPreview = ({ project }: { project: Project }) => {
    const capabilities = [
      ["Tabs", project.metadata.capabilities.tabs],
      ["Score", project.metadata.capabilities.score],
      ["Rhythm Lane", project.metadata.capabilities.rhythm],
      ["Playback", project.metadata.capabilities.playback],
    ] as const;

    return (
      <div
        className="project-capability-preview"
        aria-label="Output capabilities"
      >
        {capabilities.map(([label, available]) => (
          <span className={available ? "available" : "unavailable"} key={label}>
            {available ? (
              <Icon name="check" />
            ) : (
              <span aria-hidden="true">x</span>
            )}
            {label}
          </span>
        ))}
      </div>
    );
  };

  const ProjectMetadataBlock = ({ project }: { project: Project }) => (
    <>
      <div className="project-badge-row" aria-label="Transcription metadata">
        <span
          className={`project-stem-badge stem-tone-${project.metadata.tone}`}
        >
          {project.metadata.sourceBadge}
        </span>
        {project.metadata.outputBadges.map((badge) => (
          <span className="project-output-badge" key={badge}>
            {badge}
          </span>
        ))}
      </div>

      <div className="project-instrument-row">
        <span>
          Stem: <strong>{project.metadata.stemLabel}</strong>
        </span>
        <span>
          Instrument: <strong>{project.metadata.instrumentLabel}</strong>
        </span>
        {project.metadata.isMultiTrack && (
          <span>
            Tracks: <strong>{project.metadata.trackCount}</strong>
          </span>
        )}
      </div>

      <CapabilityPreview project={project} />
    </>
  );

  return (
    <div className="dashboard-page" ref={dashboardRef}>
      {toast && (
        <div className={`studio-toast studio-toast-${toast.tone}`}>
          {toast.message}
        </div>
      )}
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
              Welcome back, {user.username}. Turn rough audio into readable
              guitar scores, clean tabs, and exportable practice files.
            </p>
          </div>
          <div className="dashboard-header-actions">
            <button
              onClick={() => setViewMode(viewMode === "grid" ? "list" : "grid")}
              className={`view-mode-button icon-button ${viewMode === "list" ? "active" : ""}`}
              aria-label={
                viewMode === "grid"
                  ? "Switch to list view"
                  : "Switch to grid view"
              }
              title={viewMode === "grid" ? "List view" : "Grid view"}
            >
              <Icon name={viewMode === "grid" ? "list" : "grid"} />
            </button>
            <button
              onClick={handleNewTranscription}
              className="new-transcription-button"
            >
              <Icon name="plus" />
              <span>New transcription</span>
            </button>
          </div>
        </header>

        <main className="dashboard-main">
          <div className="dashboard-stats">
            {statCards.map((stat) => (
              <div
                className={`stat-card stat-card-${stat.tone}`}
                key={stat.label}
              >
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
            <h2 className="section-title">{sectionTitle}</h2>

            {loading ? (
              <div className="loading-state">
                <div className="loading-spinner"></div>
                <p className="loading-text">
                  Loading your transcription library...
                </p>
              </div>
            ) : projects.length === 0 ? (
              <div className="empty-state">
                <h3 className="empty-state-title">
                  Your first score is waiting
                </h3>
                <p className="empty-state-description">
                  Upload an MP3, WAV, or YouTube link and let the studio
                  generate guitar notation from it.
                </p>
                <button
                  onClick={handleNewTranscription}
                  className="primary-action-button"
                >
                  Start first transcription
                </button>
              </div>
            ) : featuredProject && viewMode === "grid" ? (
              <article
                className={`project-card featured-project-card project-card-${featuredProject.status}`}
                onDoubleClick={() => navigate(getProjectRoute(featuredProject))}
              >
                <ProjectCover
                  title={featuredProject.title}
                  tone={featuredProject.metadata.tone}
                />
                <div className="project-body">
                  <div className="project-card-header">
                    <h3 className="project-title">{featuredProject.title}</h3>
                    <div
                      className="project-status-badge"
                      style={{
                        background: getStatusGradient(featuredProject.status),
                      }}
                    >
                      {getStatusDisplay(featuredProject.status)}
                    </div>
                    <ProjectActionMenu
                      project={featuredProject}
                      isOpen={openMenuProjectId === featuredProject.id}
                      onToggle={() =>
                        setOpenMenuProjectId((currentId) =>
                          currentId === featuredProject.id
                            ? null
                            : featuredProject.id,
                        )
                      }
                      onAction={handleProjectAction}
                    />
                  </div>

                  <p className="project-description">
                    {featuredProject.description}
                  </p>
                  <ProjectMetadataBlock project={featuredProject} />

                  <div className="project-meta">
                    <div className="meta-item">
                      <span className="meta-label">Source</span>
                      <span className="meta-value">
                        {featuredProject.audioFileName}
                      </span>
                    </div>
                    <div className="meta-item">
                      <span className="meta-label">Duration</span>
                      <span className="meta-value">
                        {formatDuration(featuredProject.duration)}
                      </span>
                    </div>
                    <div className="meta-item">
                      <span className="meta-label">Created</span>
                      <span className="meta-value">
                        {formatCreatedDate(featuredProject.createdAt)}
                      </span>
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
                    {(featuredProject.status === "completed" ||
                      featuredProject.status === "warning") && (
                      <span className="quality-badge">
                        <Icon name="check" />
                        {featuredProject.isDemo
                          ? "example"
                          : featuredProject.status === "warning"
                            ? "Stem Ready"
                            : "export ready"}
                      </span>
                    )}
                  </div>
                </div>

                <div className="project-actions">
                  <button
                    onClick={() => navigate(getProjectRoute(featuredProject))}
                    className="action-button view-button"
                  >
                    <Icon name="eye" />
                    <span>View</span>
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
                        <ProjectCover
                          title={project.title}
                          tone={project.metadata.tone}
                        />
                        <div className="project-body">
                          <div className="project-card-header">
                            <h3 className="project-title">{project.title}</h3>
                            <div
                              className="project-status-badge"
                              style={{
                                background: getStatusGradient(project.status),
                              }}
                            >
                              {getStatusDisplay(project.status)}
                            </div>
                            <ProjectActionMenu
                              project={project}
                              isOpen={openMenuProjectId === project.id}
                              onToggle={() =>
                                setOpenMenuProjectId((currentId) =>
                                  currentId === project.id ? null : project.id,
                                )
                              }
                              onAction={handleProjectAction}
                            />
                          </div>
                          <p className="project-description">
                            {project.description}
                          </p>
                          <ProjectMetadataBlock project={project} />

                          <div className="project-meta">
                            <div className="meta-item">
                              <span className="meta-label">Source</span>
                              <span className="meta-value">
                                {project.audioFileName}
                              </span>
                            </div>
                            <div className="meta-item">
                              <span className="meta-label">Duration</span>
                              <span className="meta-value">
                                {formatDuration(project.duration)}
                              </span>
                            </div>
                            <div className="meta-item">
                              <span className="meta-label">Created</span>
                              <span className="meta-value">
                                {formatCreatedDate(project.createdAt)}
                              </span>
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
                            {(project.status === "completed" ||
                              project.status === "warning") && (
                              <span className="quality-badge">
                                <Icon name="check" />
                                {project.isDemo
                                  ? "example"
                                  : project.status === "warning"
                                    ? "Stem Ready"
                                    : "export ready"}
                              </span>
                            )}
                          </div>
                        </div>

                        <div className="project-actions">
                          <button
                            onClick={() => navigate(getProjectRoute(project))}
                            className="action-button view-button"
                          >
                            <Icon name="eye" />
                            <span>View</span>
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="projects-list">
                    {projects.map((project) => (
                      <article
                        key={project.id}
                        className={`project-list-item project-list-item-${project.status}`}
                      >
                        <ProjectCover
                          title={project.title}
                          tone={project.metadata.tone}
                        />
                        <div className="project-list-content">
                          <div className="project-list-header">
                            <h3 className="project-list-title">
                              {project.title}
                            </h3>
                            <div
                              className="project-list-status"
                              style={{
                                background: getStatusGradient(project.status),
                              }}
                            >
                              {getStatusDisplay(project.status)}
                            </div>
                            <ProjectActionMenu
                              project={project}
                              isOpen={openMenuProjectId === project.id}
                              onToggle={() =>
                                setOpenMenuProjectId((currentId) =>
                                  currentId === project.id ? null : project.id,
                                )
                              }
                              onAction={handleProjectAction}
                            />
                          </div>

                          <div className="project-list-body">
                            <p className="project-list-description">
                              {project.description}
                            </p>
                            <ProjectMetadataBlock project={project} />

                            <div className="project-list-info">
                              <div className="info-row">
                                <span className="info-label">File</span>
                                <span className="info-value">
                                  {project.audioFileName}
                                </span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Duration</span>
                                <span className="info-value">
                                  {formatDuration(project.duration)}
                                </span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Difficulty</span>
                                <span
                                  className="info-value"
                                  style={{
                                    color: getDifficultyColor(
                                      project.difficulty,
                                    ),
                                  }}
                                >
                                  {project.difficulty}
                                </span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Created</span>
                                <span className="info-value">
                                  {formatCreatedDateTime(project.createdAt)}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="project-list-actions">
                          <button
                            onClick={() => navigate(getProjectRoute(project))}
                            className="action-button list-action-button"
                          >
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
                      <ProjectCover
                        title={project.title}
                        tone={project.metadata.tone}
                      />
                      <div className="project-body">
                        <div className="project-card-header">
                          <h3 className="project-title">{project.title}</h3>
                          <div
                            className="project-status-badge"
                            style={{
                              background: getStatusGradient(project.status),
                            }}
                          >
                            {getStatusDisplay(project.status)}
                          </div>
                          <ProjectActionMenu
                            project={project}
                            isOpen={openMenuProjectId === project.id}
                            onToggle={() =>
                              setOpenMenuProjectId((currentId) =>
                                currentId === project.id ? null : project.id,
                              )
                            }
                            onAction={handleProjectAction}
                          />
                        </div>
                        <p className="project-description">
                          {project.description}
                        </p>
                        <ProjectMetadataBlock project={project} />
                        <div className="project-meta">
                          <div className="meta-item">
                            <span className="meta-label">Source</span>
                            <span className="meta-value">
                              {project.audioFileName}
                            </span>
                          </div>
                          <div className="meta-item">
                            <span className="meta-label">Duration</span>
                            <span className="meta-value">
                              {formatDuration(project.duration)}
                            </span>
                          </div>
                          <div className="meta-item">
                            <span className="meta-label">Created</span>
                            <span className="meta-value">
                              {formatCreatedDate(project.createdAt)}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="project-actions">
                        <button
                          onClick={() => navigate(getProjectRoute(project))}
                          className="action-button view-button"
                        >
                          <Icon name="eye" />
                          <span>View</span>
                        </button>
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
                <button
                  onClick={action.onClick}
                  className="quick-action-button"
                  key={action.title}
                >
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

      {deleteCandidate && (
        <div className="studio-modal-backdrop" role="presentation">
          <div
            className="studio-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-transcription-title"
          >
            <h3 id="delete-transcription-title">Delete transcription</h3>
            <p>
              {deleteCandidate.isDemo
                ? "This is a shared demo transcription and cannot be deleted."
                : "Are you sure you want to delete this transcription?"}
            </p>
            {deleteCandidate.status === "processing" && (
              <p className="studio-dialog-warning">
                Active processing cancellation is best-effort and may finish
                silently.
              </p>
            )}
            <div className="studio-dialog-actions">
              <button
                type="button"
                className="button-secondary"
                onClick={() => setDeleteCandidate(null)}
                disabled={isDeleting}
              >
                Cancel
              </button>
              <button
                type="button"
                className="button-danger"
                onClick={confirmDeleteProject}
                disabled={isDeleting || deleteCandidate.isDemo}
              >
                <Icon name="trash" />
                <span>{isDeleting ? "Deleting..." : "Delete project"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {errorCandidate && (
        <div className="studio-modal-backdrop" role="presentation">
          <div
            className="studio-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="processing-error-title"
          >
            <h3 id="processing-error-title">Processing error</h3>
            <p>
              {errorCandidate.processingError ||
                "No detailed processing error was returned."}
            </p>
            <div className="studio-dialog-actions">
              <button
                type="button"
                className="button-primary"
                onClick={() => setErrorCandidate(null)}
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

export default Dashboard;
