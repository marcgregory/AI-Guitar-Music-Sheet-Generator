import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  BriefcaseBusiness,
  Clock3,
  Crown,
  Eye,
  EyeOff,
  Gauge,
  History,
  KeyRound,
  LayoutDashboard,
  ListFilter,
  Loader2,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import audioService, {
  type AdminJob,
  type AdminJobsResponse,
} from "../../services/audioService";

const ADMIN_TOKEN_STORAGE_KEY = "musicstudio_admin_token";
type JobFilter = "all" | "queued" | "processing" | "rate_limited";

const emptyJobsResponse: AdminJobsResponse = {
  jobs: [],
  counts: {
    active: 0,
    queued: 0,
    processing: 0,
    rate_limited: 0,
  },
};

const parseApiDate = (value?: string | null): Date | null => {
  if (!value) return null;
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const date = new Date(hasTimezone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
};

const formatDateTime = (value?: string | null): string => {
  const date = parseApiDate(value);
  return date ? date.toLocaleString() : "Not set";
};

const formatRetryWindow = (value?: string | null): string => {
  const date = parseApiDate(value);
  if (!date) return "Not scheduled";
  const seconds = Math.max(0, Math.round((date.getTime() - Date.now()) / 1000));
  if (seconds <= 0) return "Due now";
  if (seconds < 90) return `${seconds}s`;
  const minutes = Math.ceil(seconds / 60);
  return `${minutes}m`;
};

const getJobTone = (job: AdminJob): string => {
  if (
    job.modal_dispatch_status === "rate_limited" ||
    job.modal_dispatch_status === "retry_queued"
  ) {
    return "rate-limited";
  }
  if (job.processing_status === "processing") return "processing";
  if (job.processing_status === "queued") return "queued";
  return "pending";
};

const statusLabel = (value?: string | null): string =>
  value ? value.replaceAll("_", " ") : "unknown";

const AdminJobsDashboard: React.FC = () => {
  const [adminToken, setAdminToken] = useState(
    () => window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) ?? "",
  );
  const [jobsResponse, setJobsResponse] =
    useState<AdminJobsResponse>(emptyJobsResponse);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);
  const [isTokenVisible, setIsTokenVisible] = useState(false);
  const [jobFilter, setJobFilter] = useState<JobFilter>("all");

  const tokenReady = adminToken.trim().length > 0;

  const loadJobs = useCallback(async () => {
    const trimmedToken = adminToken.trim();
    if (!trimmedToken) {
      setError("Enter the admin token configured on the backend.");
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, trimmedToken);
      const response = await audioService.listAdminJobs(trimmedToken);
      setJobsResponse(response);
      setLastLoadedAt(new Date());
    } catch (err: any) {
      setError(
        err.response?.data?.detail ||
          "Could not load admin jobs. Check the token and backend configuration.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [adminToken]);

  useEffect(() => {
    if (!tokenReady) return;
    void loadJobs();
    const intervalId = window.setInterval(() => {
      void loadJobs();
    }, 10000);
    return () => window.clearInterval(intervalId);
  }, [loadJobs, tokenReady]);

  const statCards = useMemo(
    () => [
      {
        label: "Active Jobs",
        value: jobsResponse.counts.active,
        description: "Currently processing",
        icon: BriefcaseBusiness,
        tone: "active",
        sparkline: "M2 31 C 8 23, 12 27, 17 18 S 28 14, 33 7 S 43 18, 50 4",
      },
      {
        label: "Processing",
        value: jobsResponse.counts.processing,
        description: "In progress",
        icon: Workflow,
        tone: "processing",
        sparkline: "M2 28 C 8 12, 13 34, 19 22 S 29 14, 34 21 S 43 24, 50 8",
      },
      {
        label: "Queued",
        value: jobsResponse.counts.queued,
        description: "Waiting in queue",
        icon: Clock3,
        tone: "queued",
        sparkline: "M2 26 C 9 18, 14 22, 20 12 S 30 5, 35 16 S 44 25, 50 9",
      },
      {
        label: "Rate Limited",
        value: jobsResponse.counts.rate_limited,
        description: "Limited by rate",
        icon: AlertTriangle,
        tone: "limited",
        sparkline: "M2 30 C 7 25, 11 19, 17 24 S 27 33, 32 18 S 43 11, 50 23",
      },
    ],
    [jobsResponse.counts],
  );

  const visibleJobs = useMemo(() => {
    if (jobFilter === "all") return jobsResponse.jobs;
    return jobsResponse.jobs.filter((job) => {
      if (jobFilter === "rate_limited") {
        return (
          job.modal_dispatch_status === "rate_limited" ||
          job.modal_dispatch_status === "retry_queued"
        );
      }
      return job.processing_status === jobFilter;
    });
  }, [jobFilter, jobsResponse.jobs]);

  const navItems = [
    { label: "Dashboard", icon: LayoutDashboard, active: true },
    { label: "Jobs", icon: Workflow },
    { label: "History", icon: History },
    { label: "API Keys", icon: KeyRound },
    { label: "Usage", icon: BarChart3 },
    { label: "Settings", icon: Settings },
  ];

  return (
    <div className="admin-jobs-page">
      <aside className="admin-ops-sidebar" aria-label="Operations navigation">
        <div className="admin-ops-brand">
          <span className="admin-ops-mark">
            <Gauge aria-hidden="true" />
          </span>
          <span>SonicText</span>
        </div>

        <nav className="admin-ops-nav">
          {navItems.map((item) => {
            const NavIcon = item.icon;
            return (
              <button
                type="button"
                className={`admin-ops-nav-item ${item.active ? "is-active" : ""}`}
                key={item.label}
              >
                <NavIcon aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="admin-upgrade-card">
          <Crown aria-hidden="true" />
          <strong>Upgrade Plan</strong>
          <p>Unlock higher limits and priority processing.</p>
          <button type="button">Upgrade Now</button>
        </div>

        <div className="admin-profile-card">
          <span>A</span>
          <div>
            <strong>Admin</strong>
            <p>admin@example.com</p>
          </div>
        </div>
      </aside>

      <main className="admin-ops-main">
        <section className="admin-jobs-header">
          <div className="admin-hero-copy">
            <p className="admin-kicker">Operations</p>
            <h1>Job Dashboard</h1>
            <p>
              Monitor and manage your transcription and analysis jobs in real
              time.
            </p>
          </div>

          <div className="admin-token-panel">
            <div className="admin-token-heading">
              <span>
                <ShieldCheck aria-hidden="true" />
                Admin Token
              </span>
              {lastLoadedAt && (
                <small>Synced {lastLoadedAt.toLocaleTimeString()}</small>
              )}
            </div>
            <div className="admin-token-row">
              <input
                id="admin-token"
                type={isTokenVisible ? "text" : "password"}
                value={adminToken}
                autoComplete="off"
                onChange={(event) => setAdminToken(event.target.value)}
                placeholder="X-Admin-Token"
                aria-label="Admin token"
              />
              <button
                type="button"
                className="admin-token-eye"
                onClick={() => setIsTokenVisible((visible) => !visible)}
                aria-label={
                  isTokenVisible ? "Hide admin token" : "Reveal admin token"
                }
              >
                {isTokenVisible ? (
                  <EyeOff aria-hidden="true" />
                ) : (
                  <Eye aria-hidden="true" />
                )}
              </button>
              <button
                type="button"
                className="admin-refresh-button"
                onClick={loadJobs}
                disabled={isLoading}
              >
                <RefreshCw aria-hidden="true" />
                <span>{isLoading ? "Loading..." : "Refresh"}</span>
              </button>
            </div>
          </div>
        </section>

        {error && <div className="alert alert-error">{error}</div>}

        <section className="admin-job-stats" aria-label="Job summary">
          {statCards.map((stat) => (
            <article
              className={`admin-job-stat admin-stat-${stat.tone}`}
              key={stat.label}
            >
              <span className="admin-stat-icon">
                <stat.icon aria-hidden="true" />
              </span>
              <span>{stat.label}</span>
              <strong>{stat.value}</strong>
              <p>{stat.description}</p>
              <svg
                className="admin-stat-sparkline"
                viewBox="0 0 52 36"
                aria-hidden="true"
              >
                <path d={stat.sparkline} />
              </svg>
            </article>
          ))}
        </section>

        <section className="admin-job-table-shell">
          <div className="admin-job-table-header">
            <div>
              <span className="admin-panel-icon">
                <ListFilter aria-hidden="true" />
              </span>
              <h2>Queued and Processing Jobs</h2>
            </div>
            <div className="admin-job-toolbar">
              <select
                value={jobFilter}
                onChange={(event) =>
                  setJobFilter(event.target.value as JobFilter)
                }
                aria-label="Filter jobs by status"
              >
                <option value="all">All Status</option>
                <option value="queued">Queued</option>
                <option value="processing">Processing</option>
                <option value="rate_limited">Rate Limited</option>
              </select>
              <span>{visibleJobs.length} jobs</span>
              <button
                type="button"
                onClick={loadJobs}
                disabled={isLoading}
                aria-label="Refresh jobs"
              >
                <RefreshCw aria-hidden="true" />
              </button>
            </div>
          </div>

          {isLoading && jobsResponse.jobs.length === 0 ? (
            <div className="admin-loading-skeleton" aria-label="Loading jobs">
              <Loader2 aria-hidden="true" />
              <span />
              <span />
              <span />
            </div>
          ) : visibleJobs.length === 0 ? (
            <div className="admin-empty-state">
              <span className="admin-empty-orbit" />
              <span className="admin-empty-illustration">
                <Sparkles aria-hidden="true" />
              </span>
              <h3>All clear!</h3>
              <p>
                No queued or processing jobs right now. New jobs will appear
                here.
              </p>
            </div>
          ) : (
            <div className="admin-job-table-scroll">
              <table className="admin-job-table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>State</th>
                    <th>Modal</th>
                    <th>Retry</th>
                    <th>Owner</th>
                    <th>Last Error</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleJobs.map((job) => (
                    <tr
                      className={`admin-job-row admin-job-${getJobTone(job)}`}
                      key={job.id}
                    >
                      <td>
                        <strong>{job.title}</strong>
                        <span>
                          #{job.id} / {job.selected_stem || "stem"} /{" "}
                          {job.modal_job_type || "process"}
                        </span>
                      </td>
                      <td>
                        <span className="admin-status-pill">
                          {statusLabel(job.processing_status)}
                        </span>
                        <small>{statusLabel(job.modal_status_detail)}</small>
                      </td>
                      <td>
                        <span>{statusLabel(job.modal_dispatch_status)}</span>
                        <small>{job.modal_request_id || "No request id"}</small>
                      </td>
                      <td>
                        <span>{job.modal_retry_count ?? 0} attempts</span>
                        <small>
                          {formatRetryWindow(job.modal_retry_at)} /{" "}
                          {formatDateTime(job.modal_retry_at)}
                        </small>
                      </td>
                      <td>
                        <span>
                          {job.user_email ||
                            `User ${job.user_id ?? "unknown"}`}
                        </span>
                        <small>Queued {formatDateTime(job.created_at)}</small>
                      </td>
                      <td>
                        <span>
                          {job.last_error || job.warning_message || "None"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default AdminJobsDashboard;
