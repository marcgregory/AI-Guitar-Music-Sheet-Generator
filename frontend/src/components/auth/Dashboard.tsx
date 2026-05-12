import React, { useState, useEffect } from "react";
import { useAuth } from "./AuthContext";
import { useNavigate } from "react-router-dom";
import { useTheme } from "../ThemeProvider";

interface Project {
  id: number;
  title: string;
  description: string;
  createdAt: string;
  audioFileName: string;
  status: "processing" | "completed" | "failed";
  duration: number; // in seconds
  difficulty: "beginner" | "intermediate" | "advanced";
}

const Dashboard: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { toggleDarkMode, isDarkMode } = useTheme();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const handleNewTranscription = () => {
    navigate("/upload");
  };

  const handleViewModeChange = (mode: "grid" | "list") => {
    setViewMode(mode);
  };

  // Mock data - in a real app, this would come from an API
  useEffect(() => {
    const loadProjects = async () => {
      try {
        // Simulate API call
        await new Promise((resolve) => setTimeout(resolve, 800));

        // Mock data with rich details
        const mockProjects: Project[] = [
          {
            id: 1,
            title: "Hotel California - Eagles",
            description:
              "Classic rock song with iconic guitar solo and complex chord progression",
            createdAt: "2026-05-10T14:30:00Z",
            audioFileName: "hotel_california.mp3",
            status: "completed",
            duration: 391,
            difficulty: "advanced",
          },
          {
            id: 2,
            title: "Stairway to Heaven - Led Zeppelin",
            description:
              "Legendary progressive rock anthem with intricate fingerpicking",
            createdAt: "2026-05-09T09:15:00Z",
            audioFileName: "stairway_to_heaven.wav",
            status: "completed",
            duration: 482,
            difficulty: "advanced",
          },
          {
            id: 3,
            title: "Wonderwall - Oasis",
            description:
              "Popular acoustic track with memorable strumming pattern",
            createdAt: "2026-05-08T16:45:00Z",
            audioFileName: "wonderwall.mp3",
            status: "completed",
            duration: 258,
            difficulty: "intermediate",
          },
          {
            id: 4,
            title: "New Project",
            description: "Recently uploaded audio file awaiting processing",
            createdAt: new Date().toISOString(),
            audioFileName: "unknown.mp3",
            status: "processing",
            duration: 0,
            difficulty: "beginner",
          },
        ];

        setProjects(mockProjects);
        setLoading(false);
      } catch (error) {
        console.error("Failed to load projects:", error);
        setLoading(false);
      }
    };

    loadProjects();
  }, []);

  if (!user) {
    navigate("/login");
    return null;
  }

  // Generate a gradient based on project status
  const getStatusGradient = (status: string) => {
    switch (status) {
      case "completed":
        return "linear-gradient(135deg, #10b981, #059669)";
      case "processing":
        return "linear-gradient(135deg, #f59e0b, #d97706)";
      case "failed":
        return "linear-gradient(135deg, #ef4444, #dc2626)";
      default:
        return "linear-gradient(135deg, #6b7280, #4b5563)";
    }
  };

  // Get difficulty color
  const getDifficultyColor = (difficulty: string) => {
    switch (difficulty) {
      case "beginner":
        return "#10b981";
      case "intermediate":
        return "#f59e0b";
      case "advanced":
        return "#ef4444";
      default:
        return "#6b7280";
    }
  };

  return (
    <div className="dashboard-page">
      {/* Animated background */}
      <div className="dashboard-background">
        <div className="dashboard-background-shapes"></div>
      </div>

      <div className="dashboard-content">
        <header className="dashboard-header">
          <div className="dashboard-header-content">
            <h1 className="dashboard-title">
              <span className="title-icon">🎵</span>
              MusicSheet Generator
            </h1>
            <p className="dashboard-subtitle">
              Welcome back, {user.username}! Transform audio into guitar tabs
              with AI
            </p>
          </div>
          <div className="dashboard-header-actions">
            <button
              onClick={handleViewModeChange}
              className={`view-mode-button ${viewMode === "list" ? "active" : ""}`}
              title={viewMode === "grid" ? "List View" : "Grid View"}
            >
              {viewMode === "grid" ? "📊" : "🧱"}
            </button>
            <button
              onClick={handleNewTranscription}
              className="new-transcription-button"
            >
              <span className="button-icon">✨</span>
              <span>New Transcription</span>
            </button>
            <button onClick={handleLogout} className="logout-button">
              <span className="button-icon">🚪</span>
              <span>Logout</span>
            </button>
            <button
              onClick={toggleDarkMode}
              className="theme-toggle-button"
              title="Toggle Dark/Light Mode"
            >
              <span className="button-icon">{isDarkMode ? "☀️" : "🌙"}</span>
            </button>
          </div>
        </header>

        <main className="dashboard-main">
          {/* Stats Overview */}
          <div className="dashboard-stats">
            <div className="stat-card">
              <div className="stat-icon">📊</div>
              <div className="stat-content">
                <h3 className="stat-value">{projects.length}</h3>
                <p className="stat-label">Total Projects</p>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-icon">✅</div>
              <div className="stat-content">
                <h3 className="stat-value">
                  {projects.filter((p) => p.status === "completed").length}
                </h3>
                <p className="stat-label">Completed</p>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-icon">⏳</div>
              <div className="stat-content">
                <h3 className="stat-value">
                  {projects.filter((p) => p.status === "processing").length}
                </h3>
                <p className="stat-label">Processing</p>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-icon">⏱️</div>
              <div className="stat-content">
                <h3 className="stat-value">
                  {Math.floor(
                    projects.reduce((sum, p) => sum + p.duration, 0) / 60,
                  )}
                  h
                </h3>
                <p className="stat-label">Total Time</p>
              </div>
            </div>
          </div>

          {/* Projects Section */}
          <section className="projects-section">
            <h2 className="section-title">
              <span className="section-icon">📁</span>
              Your Music Projects
            </h2>

            {loading ? (
              <div className="loading-state">
                <div className="loading-spinner"></div>
                <p className="loading-text">
                  Loading your musical creations...
                </p>
              </div>
            ) : projects.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">🎧</div>
                <h3 className="empty-state-title">No projects yet</h3>
                <p className="empty-state-description">
                  Your first transcription awaits. Upload an audio file to begin
                  your journey.
                </p>
                <button
                  onClick={handleNewTranscription}
                  className="primary-action-button"
                >
                  Start First Transcription
                </button>
              </div>
            ) : (
              <div className={`projects-container ${viewMode}`}>
                {viewMode === "grid" ? (
                  <div className="projects-grid">
                    {projects.map((project) => (
                      <div
                        key={project.id}
                        className={`project-card project-card-${project.status}`}
                        onDoubleClick={() => navigate(`/project/${project.id}`)}
                      >
                        <div className="project-card-header">
                          <div
                            className="project-status-badge"
                            style={{
                              background: getStatusGradient(project.status),
                            }}
                          >
                            {project.status.toUpperCase()}
                          </div>
                          <h3 className="project-title">{project.title}</h3>
                        </div>

                        <div className="project-body">
                          <p className="project-description">
                            {project.description}
                          </p>

                          <div className="project-meta">
                            <div className="meta-item">
                              <span className="meta-icon">📄</span>
                              <span>{project.audioFileName}</span>
                            </div>
                            <div className="meta-item">
                              <span className="meta-icon">⏱️</span>
                              <span>
                                {Math.floor(project.duration / 60)}:
                                {String(project.duration % 60).padStart(2, "0")}
                              </span>
                            </div>
                            <div className="meta-item">
                              <span className="meta-icon">📅</span>
                              <span>
                                {new Date(
                                  project.createdAt,
                                ).toLocaleDateString()}
                              </span>
                            </div>
                          </div>

                          <div className="project-tags">
                            <span
                              className="difficulty-tag"
                              style={{
                                backgroundColor:
                                  getDifficultyColor(project.difficulty) + "20",
                                color: getDifficultyColor(project.difficulty),
                              }}
                            >
                              {project.difficulty.toUpperCase()}
                            </span>
                            {project.status === "completed" && (
                              <span className="quality-badge">HD Quality</span>
                            )}
                          </div>
                        </div>

                        <div className="project-actions">
                          <button
                            onClick={() => navigate(`/project/${project.id}`)}
                            className="action-button view-button"
                          >
                            <span className="button-icon">👁️</span>
                            <span>View Details</span>
                          </button>
                          {project.status === "completed" && (
                            <>
                              <button
                                onClick={() =>
                                  alert("Export functionality coming soon!")
                                }
                                className="action-button export-button"
                              >
                                <span className="button-icon">📥</span>
                                <span>Export</span>
                              </button>
                              <button
                                onClick={() =>
                                  alert("Share functionality coming soon!")
                                }
                                className="action-button share-button"
                              >
                                <span className="button-icon">🔗</span>
                                <span>Share</span>
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="projects-list">
                    {projects.map((project) => (
                      <div
                        key={project.id}
                        className={`project-list-item project-list-item-${project.status}`}
                      >
                        <div className="project-list-content">
                          <div className="project-list-header">
                            <h3 className="project-list-title">
                              {project.title}
                            </h3>
                            <div
                              className="project-list-status"
                              style={{
                                background: getStatusGradient(project.status),
                                color: "white",
                              }}
                            >
                              {project.status.toUpperCase()}
                            </div>
                          </div>

                          <div className="project-list-body">
                            <p className="project-list-description">
                              {project.description}
                            </p>

                            <div className="project-list-info">
                              <div className="info-row">
                                <span className="info-label">File:</span>
                                <span className="info-value">
                                  {project.audioFileName}
                                </span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Duration:</span>
                                <span className="info-value">
                                  {Math.floor(project.duration / 60)}:
                                  {String(project.duration % 60).padStart(
                                    2,
                                    "0",
                                  )}
                                </span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Difficulty:</span>
                                <span
                                  className="info-value"
                                  style={{
                                    color: getDifficultyColor(
                                      project.difficulty,
                                    ),
                                    fontWeight: "600",
                                  }}
                                >
                                  {project.difficulty.toUpperCase()}
                                </span>
                              </div>
                              <div className="info-row">
                                <span className="info-label">Created:</span>
                                <span className="info-value">
                                  {new Date(project.createdAt).toLocaleString()}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="project-list-actions">
                          <button
                            onClick={() => navigate(`/project/${project.id}`)}
                            className="action-button list-action-button"
                          >
                            View Details
                          </button>
                          {project.status === "completed" && (
                            <button
                              onClick={() => alert("Export coming soon!")}
                              className="action-button list-action-button export-button"
                            >
                              Export
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Quick Actions */}
          <section className="quick-actions-section">
            <h2 className="section-title">
              <span className="section-icon">⚡</span>
              Quick Actions
            </h2>
            <div className="quick-actions-grid">
              <button
                onClick={handleNewTranscription}
                className="quick-action-button"
              >
                <div className="quick-action-icon">📤</div>
                <div className="quick-action-content">
                  <h3>Upload Audio</h3>
                  <p>MP3, WAV, or YouTube URL</p>
                </div>
              </button>

              <button
                onClick={() => alert("Recording feature coming soon!")}
                className="quick-action-button"
              >
                <div className="quick-action-icon">🎤</div>
                <div class="quick-action-content">
                  <h3>Record Audio</h3>
                  <p>Capture directly from mic</p>
                </div>
              </button>

              <button
                onClick={() => alert("Batch processing coming soon!")}
                className="quick-action-button"
              >
                <div className="quick-action-icon">📦</div>
                <div class="quick-action-content">
                  <h3>Batch Process</h3>
                  <p>Multiple files at once</p>
                </div>
              </button>

              <button
                onClick={() => alert("Template library coming soon!")}
                className="quick-action-button"
              >
                <div className="quick-action-icon">📋</div>
                <div class="quick-action-content">
                  <h3>Templates</h3>
                  <p>Start with presets</p>
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
