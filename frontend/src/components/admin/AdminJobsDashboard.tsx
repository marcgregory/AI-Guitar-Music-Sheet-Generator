import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  Activity,
  AudioLines,
  BarChart3,
  BriefcaseBusiness,
  ChevronDown,
  Clock3,
  ClipboardCheck,
  Crown,
  Eye,
  EyeOff,
  History,
  KeyRound,
  LayoutDashboard,
  Loader2,
  RefreshCw,
  RotateCcw,
  Settings,
  ShieldCheck,
} from "lucide-react";
import audioService, {
  type AdminJob,
  type AdminJobHistoryResponse,
  type AdminJobHistoryStatus,
  type AdminJobsResponse,
  type AdminUsageResponse,
  type AdminUsageRow,
} from "../../services/audioService";
import { API_BASE_URL } from "../../services/apiClient";
import { ADMIN_TOKEN_STORAGE_KEY } from "../../utils/adminAccess";
type JobFilter = "all" | "queued" | "processing" | "rate_limited";
type AdminJobsView = "active" | "history";
type HistoryStatusFilter = "all" | AdminJobHistoryStatus;
type HistoryLimit = 25 | 50 | 100;

type AdminFilterOption<T extends string | number> = {
  label: string;
  value: T;
};

type AdminFilterSelectProps<T extends string | number> = {
  "aria-label": string;
  options: AdminFilterOption<T>[];
  value: T;
  onChange: (value: T) => void;
};

const emptyJobsResponse: AdminJobsResponse = {
  jobs: [],
  counts: {
    active: 0,
    queued: 0,
    processing: 0,
    rate_limited: 0,
  },
};

const emptyJobHistoryResponse: AdminJobHistoryResponse = {
  jobs: [],
  count: 0,
};

const emptyUsageResponse: AdminUsageResponse = {
  date: "",
  usage: [],
  reset_available: false,
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

const formatAdminJobsError = (error: unknown, fallback: string): string => {
  const err = error as {
    code?: string;
    message?: string;
    request?: unknown;
    response?: {
      status?: number;
      data?: {
        detail?: unknown;
      };
    };
  };
  const status = err.response?.status;
  const detail = err.response?.data?.detail;

  if (status === 403) {
    return "Invalid admin token (403). Use Forget admin token, then paste the current backend ADMIN_API_TOKEN.";
  }

  if (detail === "Admin API is not configured.") {
    return "Admin API is disabled on this backend (503). Set ADMIN_API_TOKEN and restart the backend so startup logs show Admin API configured=True.";
  }

  if (status === 503) {
    return "Admin API is unavailable on this backend (503). Check ADMIN_API_TOKEN and restart the backend.";
  }

  if (
    err.code === "ECONNABORTED" ||
    /timeout/i.test(err.message ?? "")
  ) {
    return `Admin jobs request timed out. Confirm the backend is running at ${API_BASE_URL} and try again.`;
  }

  if (err.request && !err.response) {
    return `Could not reach the admin API at ${API_BASE_URL}. Check that the backend is running and CORS allows this frontend.`;
  }

  return typeof detail === "string" && detail.trim().length > 0
    ? `${detail}${status ? ` (${status})` : ""}`
    : fallback;
};

const isTransientAdminJobsError = (error: unknown): boolean => {
  const err = error as {
    code?: string;
    message?: string;
    request?: unknown;
    response?: unknown;
  };

  return Boolean(
    err.code === "ECONNABORTED" ||
      /timeout/i.test(err.message ?? "") ||
      (err.request && !err.response),
  );
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

const formatDuration = (seconds?: number | null): string => {
  if (seconds === null || seconds === undefined) return "Unknown";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
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
  if (job.processing_status === "failed") return "failed";
  return "pending";
};

const statusLabel = (value?: string | null): string =>
  value ? value.replaceAll("_", " ") : "unknown";

const formatQuota = (row: AdminUsageRow): string =>
  row.daily_limit > 0
    ? `${row.usage_count} / ${row.daily_limit}`
    : `${row.usage_count} / unlimited`;

const AdminFilterSelect = <T extends string | number>({
  "aria-label": ariaLabel,
  options,
  value,
  onChange,
}: AdminFilterSelectProps<T>) => {
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(() =>
    Math.max(
      0,
      options.findIndex((option) => option.value === value),
    ),
  );
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const selectedOption =
    options.find((option) => option.value === value) ?? options[0];
  const listboxId = `admin-filter-${ariaLabel
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")}`;

  useEffect(() => {
    setActiveIndex(
      Math.max(
        0,
        options.findIndex((option) => option.value === value),
      ),
    );
  }, [options, value]);

  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isOpen]);

  const commitValue = (nextIndex: number) => {
    const nextOption = options[nextIndex];
    if (!nextOption) return;
    onChange(nextOption.value);
    setIsOpen(false);
    buttonRef.current?.focus();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex = (activeIndex + direction + options.length) % options.length;
      setActiveIndex(nextIndex);
      setIsOpen(true);
      return;
    }

    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setActiveIndex(event.key === "Home" ? 0 : options.length - 1);
      setIsOpen(true);
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (isOpen) {
        commitValue(activeIndex);
      } else {
        setIsOpen(true);
      }
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
    }
  };

  return (
    <div
      className={`admin-filter-select-shell ${isOpen ? "is-open" : ""}`}
      ref={rootRef}
    >
      <select
        className="admin-filter-native"
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        aria-label={ariaLabel}
        tabIndex={-1}
      >
        {options.map((option) => (
          <option key={String(option.value)} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <button
        ref={buttonRef}
        type="button"
        className="admin-filter-select"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={`${ariaLabel}: ${selectedOption.label}`}
        aria-controls={listboxId}
        aria-activedescendant={`${listboxId}-${activeIndex}`}
        onClick={() => setIsOpen((current) => !current)}
        onKeyDown={handleKeyDown}
      >
        <span>{selectedOption.label}</span>
        <ChevronDown className="admin-filter-chevron" aria-hidden="true" />
      </button>
      <div
        id={listboxId}
        className="admin-filter-menu"
        role="listbox"
        aria-label={`${ariaLabel} options`}
        aria-hidden={!isOpen}
      >
        {options.map((option, index) => {
          const isSelected = option.value === value;
          const isActive = index === activeIndex;
          return (
            <button
              key={String(option.value)}
              id={`${listboxId}-${index}`}
              type="button"
              className={`admin-filter-option ${isSelected ? "is-selected" : ""} ${
                isActive ? "is-active" : ""
              }`}
              role="option"
              aria-selected={isSelected}
              tabIndex={isOpen ? 0 : -1}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => commitValue(index)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};

const AdminJobsDashboard: React.FC = () => {
  const [adminToken, setAdminToken] = useState(
    () => window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) ?? "",
  );
  const [jobsResponse, setJobsResponse] =
    useState<AdminJobsResponse>(emptyJobsResponse);
  const [jobHistoryResponse, setJobHistoryResponse] =
    useState<AdminJobHistoryResponse>(emptyJobHistoryResponse);
  const [usageResponse, setUsageResponse] =
    useState<AdminUsageResponse>(emptyUsageResponse);
  const [isLoading, setIsLoading] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isUsageLoading, setIsUsageLoading] = useState(false);
  const [resettingUsageUserId, setResettingUsageUserId] = useState<number | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);
  const [isTokenVisible, setIsTokenVisible] = useState(false);
  const [jobFilter, setJobFilter] = useState<JobFilter>("all");
  const [activeView, setActiveView] = useState<AdminJobsView>("active");
  const [historyStatusFilter, setHistoryStatusFilter] =
    useState<HistoryStatusFilter>("all");
  const [historyLimit, setHistoryLimit] = useState<HistoryLimit>(50);
  const [usageUserIdFilter, setUsageUserIdFilter] = useState("");
  const [usageDateFilter, setUsageDateFilter] = useState("");
  const isJobsRequestInFlightRef = useRef(false);
  const isUsageRequestInFlightRef = useRef(false);
  const lastSuccessfulJobsLoadRef = useRef<Date | null>(null);
  const lastSuccessfulUsageLoadRef = useRef<Date | null>(null);

  const tokenReady = adminToken.trim().length > 0;

  const loadJobs = useCallback(async (options?: { background?: boolean }) => {
    const trimmedToken = adminToken.trim();
    if (!trimmedToken) {
      setError("Enter the admin token configured on the backend.");
      return;
    }
    if (isJobsRequestInFlightRef.current) return;

    const isBackground = Boolean(options?.background);
    isJobsRequestInFlightRef.current = true;
    setIsLoading(true);
    if (!isBackground) {
      setError(null);
    }
    try {
      window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, trimmedToken);
      const response = await audioService.listAdminJobs(trimmedToken);
      const loadedAt = new Date();
      setJobsResponse(response);
      setLastLoadedAt(loadedAt);
      lastSuccessfulJobsLoadRef.current = loadedAt;
      setError(null);
    } catch (err: any) {
      if (
        isBackground &&
        lastSuccessfulJobsLoadRef.current &&
        isTransientAdminJobsError(err)
      ) {
        return;
      }
      setError(
        formatAdminJobsError(
          err,
          "Could not load admin jobs. Check the token and backend configuration.",
        ),
      );
    } finally {
      isJobsRequestInFlightRef.current = false;
      setIsLoading(false);
    }
  }, [adminToken]);

  const loadUsage = useCallback(async (options?: { background?: boolean }) => {
    const trimmedToken = adminToken.trim();
    if (!trimmedToken) {
      setError("Enter the admin token configured on the backend.");
      return;
    }
    if (isUsageRequestInFlightRef.current) return;

    const trimmedUserId = usageUserIdFilter.trim();
    const parsedUserId =
      trimmedUserId.length > 0 ? Number.parseInt(trimmedUserId, 10) : undefined;
    if (
      trimmedUserId.length > 0 &&
      (!/^\d+$/.test(trimmedUserId) ||
        !Number.isInteger(parsedUserId) ||
        parsedUserId === undefined ||
        parsedUserId < 1)
    ) {
      setError("Usage user id must be a positive number.");
      return;
    }

    const isBackground = Boolean(options?.background);
    isUsageRequestInFlightRef.current = true;
    setIsUsageLoading(true);
    if (!isBackground) {
      setError(null);
    }
    try {
      window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, trimmedToken);
      const response = await audioService.listAdminUsage(trimmedToken, {
        userId: parsedUserId,
        date: usageDateFilter || undefined,
      });
      setUsageResponse(response);
      const loadedAt = new Date();
      setLastLoadedAt(loadedAt);
      lastSuccessfulUsageLoadRef.current = loadedAt;
    } catch (err: any) {
      if (
        isBackground &&
        lastSuccessfulUsageLoadRef.current &&
        isTransientAdminJobsError(err)
      ) {
        return;
      }
      setError(
        formatAdminJobsError(
          err,
          "Could not load usage limits. Check the token and backend configuration.",
        ),
      );
    } finally {
      isUsageRequestInFlightRef.current = false;
      setIsUsageLoading(false);
    }
  }, [adminToken, usageDateFilter, usageUserIdFilter]);

  const loadJobHistory = useCallback(async () => {
    const trimmedToken = adminToken.trim();
    if (!trimmedToken) {
      setError("Enter the admin token configured on the backend.");
      return;
    }

    setIsHistoryLoading(true);
    setError(null);
    try {
      window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, trimmedToken);
      const response = await audioService.listAdminJobHistory(trimmedToken, {
        status:
          historyStatusFilter === "all" ? undefined : historyStatusFilter,
        limit: historyLimit,
      });
      setJobHistoryResponse(response);
      setLastLoadedAt(new Date());
    } catch (err: any) {
      setError(
        formatAdminJobsError(
          err,
          "Could not load job history. Check the token and backend configuration.",
        ),
      );
    } finally {
      setIsHistoryLoading(false);
    }
  }, [adminToken, historyLimit, historyStatusFilter]);

  const forgetAdminToken = useCallback(() => {
    window.localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    setAdminToken("");
    setError(null);
    setJobsResponse(emptyJobsResponse);
    setJobHistoryResponse(emptyJobHistoryResponse);
    setUsageResponse(emptyUsageResponse);
    setUsageUserIdFilter("");
    setUsageDateFilter("");
    setLastLoadedAt(null);
  }, []);

  const handleResetUsage = useCallback(async (row: AdminUsageRow) => {
    const trimmedToken = adminToken.trim();
    if (!trimmedToken) {
      setError("Enter the admin token configured on the backend.");
      return;
    }
    const confirmed = window.confirm(
      `Reset today's usage counter for ${row.username}? This will not clear active jobs or delete transcriptions.`,
    );
    if (!confirmed) return;

    setResettingUsageUserId(row.user_id);
    setError(null);
    try {
      window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, trimmedToken);
      const response = await audioService.resetAdminUsage(
        trimmedToken,
        row.user_id,
      );
      setUsageResponse((current) => ({
        ...current,
        usage: current.usage.map((item) =>
          item.user_id === response.usage.user_id ? response.usage : item,
        ),
      }));
      setLastLoadedAt(new Date());
    } catch (err: any) {
      setError(
        formatAdminJobsError(
          err,
          "Could not reset usage limits. Check the token and backend configuration.",
        ),
      );
    } finally {
      setResettingUsageUserId(null);
    }
  }, [adminToken]);

  useEffect(() => {
    if (!tokenReady) return;
    void loadJobs();
    void loadUsage();
    const intervalId = window.setInterval(() => {
      void loadJobs({ background: true });
      void loadUsage({ background: true });
    }, 30000);
    return () => window.clearInterval(intervalId);
  }, [loadJobs, loadUsage, tokenReady]);

  useEffect(() => {
    if (!tokenReady || activeView !== "history") return;
    void loadJobHistory();
  }, [activeView, loadJobHistory, tokenReady]);

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
        icon: Activity,
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

  const navItems: {
    label: string;
    icon: typeof LayoutDashboard;
    view?: AdminJobsView;
  }[] = [
    { label: "Dashboard", icon: LayoutDashboard },
    { label: "Jobs", icon: BriefcaseBusiness, view: "active" as const },
    { label: "History", icon: History, view: "history" as const },
    { label: "API Keys", icon: KeyRound },
    { label: "Usage", icon: BarChart3 },
    { label: "Settings", icon: Settings },
  ];

  const isViewingHistory = activeView === "history";
  const currentJobs = isViewingHistory ? jobHistoryResponse.jobs : visibleJobs;
  const primaryRefreshLabel =
    isUsageLoading || (isViewingHistory ? isHistoryLoading : isLoading)
      ? "Loading..."
      : "Refresh";

  return (
    <div className="admin-jobs-page">
      <aside className="admin-ops-sidebar sidebar" aria-label="Operations navigation">
        <div className="admin-ops-brand">
          <span className="admin-ops-mark">
            <AudioLines aria-hidden="true" />
          </span>
          <span>SonicText</span>
        </div>

        <nav className="admin-ops-nav">
          {navItems.map((item) => {
            const NavIcon = item.icon;
            return (
              <button
                type="button"
                className={`admin-ops-nav-item ${item.view === activeView ? "is-active" : ""}`}
                key={item.label}
                onClick={() => {
                  if (!item.view) return;
                  setActiveView(item.view);
                }}
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

      <main className="admin-ops-main main-content">
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
                onClick={() => {
                  if (isViewingHistory) {
                    void loadJobHistory();
                  } else {
                    void loadJobs();
                  }
                  void loadUsage();
                }}
                disabled={
                  (isViewingHistory ? isHistoryLoading : isLoading) ||
                  isUsageLoading
                }
              >
                <RefreshCw aria-hidden="true" />
                <span>{primaryRefreshLabel}</span>
              </button>
              <button
                type="button"
                className="admin-forget-token-button"
                onClick={forgetAdminToken}
              >
                Forget admin token
              </button>
            </div>
            {!tokenReady && (
              <p className="admin-token-hint">
                Enter the backend ADMIN_API_TOKEN to view operations jobs.
              </p>
            )}
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

        <section className="admin-usage-panel" aria-label="Usage limits">
          <div className="admin-job-table-header">
            <div>
              <span className="admin-panel-icon">
                <BarChart3 aria-hidden="true" />
              </span>
              <h2>Usage Limits</h2>
            </div>
            <div className="admin-job-toolbar">
              <label className="admin-usage-filter">
                <span>User ID</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min="1"
                  placeholder="All"
                  value={usageUserIdFilter}
                  onChange={(event) => setUsageUserIdFilter(event.target.value)}
                  aria-label="Filter usage by user id"
                />
              </label>
              <label className="admin-usage-filter">
                <span>Date</span>
                <input
                  type="date"
                  value={usageDateFilter}
                  onChange={(event) => setUsageDateFilter(event.target.value)}
                  aria-label="Filter usage by UTC date"
                />
              </label>
              <span>
                {usageResponse.date
                  ? `UTC ${usageResponse.date}`
                  : "UTC today"}
              </span>
              <button
                type="button"
                onClick={() => {
                  void loadUsage();
                }}
                disabled={isUsageLoading}
                aria-label="Refresh usage limits"
              >
                <RefreshCw aria-hidden="true" />
              </button>
            </div>
          </div>

          {isUsageLoading && usageResponse.usage.length === 0 ? (
            <div className="admin-loading-skeleton" aria-label="Loading usage limits">
              <Loader2 aria-hidden="true" />
              <span />
              <span />
              <span />
            </div>
          ) : usageResponse.usage.length === 0 ? (
            <div className="admin-usage-empty">
              <strong>No usage limits are active for this UTC day.</strong>
              <span>Users with quota usage or active jobs will appear here.</span>
            </div>
          ) : (
            <div className="admin-usage-grid">
              {usageResponse.usage.map((row) => {
                const quotaUsed =
                  row.daily_limit > 0
                    ? Math.min(100, (row.usage_count / row.daily_limit) * 100)
                    : 0;
                const isResetting = resettingUsageUserId === row.user_id;
                return (
                  <article className="admin-usage-card" key={row.user_id}>
                    <div className="admin-usage-card-header">
                      <div>
                        <strong>{row.username}</strong>
                        <span>User {row.user_id}</span>
                      </div>
                      <span
                        className={`admin-usage-quota ${
                          row.remaining_quota === 0 ? "is-exhausted" : ""
                        }`}
                      >
                        {formatQuota(row)}
                      </span>
                    </div>
                    <div className="admin-usage-meter" aria-hidden="true">
                      <span style={{ width: `${quotaUsed}%` }} />
                    </div>
                    <div className="admin-usage-facts">
                      <span>
                        <strong>{row.remaining_quota}</strong>
                        Remaining
                      </span>
                      <span>
                        <strong>{row.active_job_count}</strong>
                        Active jobs
                      </span>
                    </div>
                    {row.reset_available && (
                      <button
                        type="button"
                        className="admin-usage-reset"
                        onClick={() => {
                          void handleResetUsage(row);
                        }}
                        disabled={isResetting}
                      >
                        {isResetting ? (
                          <Loader2 aria-hidden="true" />
                        ) : (
                          <RotateCcw aria-hidden="true" />
                        )}
                        <span>{isResetting ? "Resetting..." : "Reset usage"}</span>
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="admin-job-table-shell">
          <div className="admin-job-table-header">
            <div>
              <span className="admin-panel-icon">
                {isViewingHistory ? (
                  <History aria-hidden="true" />
                ) : (
                  <BriefcaseBusiness aria-hidden="true" />
                )}
              </span>
              <h2>
                {isViewingHistory
                  ? "Recent Completed and Failed Jobs"
                  : "Queued and Processing Jobs"}
              </h2>
            </div>
            <div className="admin-job-toolbar">
              {isViewingHistory ? (
                <>
                  <AdminFilterSelect
                    value={historyStatusFilter}
                    onChange={(value) =>
                      setHistoryStatusFilter(
                        value as HistoryStatusFilter,
                      )
                    }
                    aria-label="Filter history by status"
                    options={[
                      { value: "all", label: "All" },
                      { value: "completed", label: "Completed" },
                      {
                        value: "completed_with_warning",
                        label: "Completed with warning",
                      },
                      { value: "failed", label: "Failed" },
                    ]}
                  />
                  <AdminFilterSelect
                    value={historyLimit}
                    onChange={(value) =>
                      setHistoryLimit(Number(value) as HistoryLimit)
                    }
                    aria-label="Limit history jobs"
                    options={[
                      { value: 25, label: "25" },
                      { value: 50, label: "50" },
                      { value: 100, label: "100" },
                    ]}
                  />
                  <span>{jobHistoryResponse.count} jobs</span>
                </>
              ) : (
                <>
                  <AdminFilterSelect
                    value={jobFilter}
                    onChange={(value) =>
                      setJobFilter(value as JobFilter)
                    }
                    aria-label="Filter jobs by status"
                    options={[
                      { value: "all", label: "All Status" },
                      { value: "queued", label: "Queued" },
                      { value: "processing", label: "Processing" },
                      { value: "rate_limited", label: "Rate Limited" },
                    ]}
                  />
                  <span>{visibleJobs.length} jobs</span>
                </>
              )}
              <button
                type="button"
                onClick={() => {
                  void (isViewingHistory ? loadJobHistory() : loadJobs());
                }}
                disabled={isViewingHistory ? isHistoryLoading : isLoading}
                aria-label={isViewingHistory ? "Refresh job history" : "Refresh jobs"}
              >
                <RefreshCw aria-hidden="true" />
              </button>
            </div>
          </div>

          {(isViewingHistory ? isHistoryLoading : isLoading) &&
          currentJobs.length === 0 ? (
            <div className="admin-loading-skeleton" aria-label="Loading jobs">
              <Loader2 aria-hidden="true" />
              <span />
              <span />
              <span />
            </div>
          ) : currentJobs.length === 0 ? (
            <div className="admin-empty-state">
              <span className="admin-empty-orbit" />
              <span className="admin-empty-illustration">
                <ClipboardCheck aria-hidden="true" />
              </span>
              <h3>{isViewingHistory ? "No history yet" : "All clear!"}</h3>
              <p>
                {isViewingHistory
                  ? "Completed and failed Modal jobs will appear here after callbacks finish."
                  : "No queued or processing jobs right now. New jobs will appear here."}
              </p>
            </div>
          ) : (
            <div className="admin-job-table-scroll">
              <table className="admin-job-table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>{isViewingHistory ? "Final Status" : "State"}</th>
                    <th>Modal</th>
                    <th>{isViewingHistory ? "Duration" : "Retry"}</th>
                    <th>Owner</th>
                    <th>Last Error</th>
                  </tr>
                </thead>
                <tbody>
                  {currentJobs.map((job) => (
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
                        {isViewingHistory ? (
                          <>
                            <span>{formatDuration(job.duration_seconds)}</span>
                            <small>Retries {job.modal_retry_count ?? 0}</small>
                          </>
                        ) : (
                          <>
                            <span>{job.modal_retry_count ?? 0} attempts</span>
                            <small>
                              {formatRetryWindow(job.modal_retry_at)} /{" "}
                              {formatDateTime(job.modal_retry_at)}
                            </small>
                          </>
                        )}
                      </td>
                      <td>
                        <span>
                          {job.user_email ||
                            `User ${job.user_id ?? "unknown"}`}
                        </span>
                        <small>
                          {isViewingHistory ? "Finished" : "Queued"}{" "}
                          {formatDateTime(job.updated_at || job.created_at)}
                        </small>
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
