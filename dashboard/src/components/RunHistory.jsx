import { useState, useEffect, useCallback } from "react";

/**
 * RunHistory — Multi-tenant historical execution telemetry.
 * Displays previous test runs with search, status filtering, project context,
 * pass/fail trends, error diagnostics, and deep links to inspect results.
 */

const STATUS_COLORS = {
  queued:    { bg: "rgba(245, 158, 11, 0.12)", color: "var(--warning, #f59e0b)", label: "Queued" },
  running:  { bg: "var(--brand-surface)", color: "var(--brand-primary)", label: "Running" },
  completed:{ bg: "rgba(16, 185, 129, 0.12)", color: "var(--success, #10b981)", label: "Completed" },
  failed:   { bg: "rgba(244, 63, 94, 0.12)", color: "var(--danger, #f43f5e)", label: "Failed" },
  cancelled:{ bg: "var(--bg-subtle)", color: "var(--text-muted)", label: "Cancelled" },
};

function StatusBadge({ status }) {
  const cfg = STATUS_COLORS[status] || STATUS_COLORS.queued;
  return (
    <span
      style={{
        fontSize: 10.5,
        fontWeight: 700,
        padding: "2px 8px",
        borderRadius: "var(--r-full, 999px)",
        background: cfg.bg,
        color: cfg.color,
        border: `1px solid ${cfg.color}30`,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
        whiteSpace: "nowrap",
      }}
    >
      {cfg.label}
    </span>
  );
}

export function RunHistory({
  apiBaseUrl,
  token,
  selectedProject,
  onLoadRun,
  onViewActiveRun,
  onError,
  onLogout,
}) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all"); // all, active, completed, failed
  const [search, setSearch] = useState("");

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedProject?.id) params.set("project_id", selectedProject.id);
      const url = `${apiBaseUrl}/test-runs${params.toString() ? `?${params}` : ""}`;
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.status === 401) {
        onLogout?.();
        return;
      }
      if (!res.ok) throw new Error("Failed to load run history.");
      const json = await res.json();
      setRuns(json.data || []);
    } catch (err) {
      onError?.(err.message || "Cannot load run history.");
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, token, selectedProject?.id, onLogout, onError]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Filter and search logic
  const filtered = runs.filter((r) => {
    if (filter === "completed" && r.status !== "completed") return false;
    if (filter === "failed" && r.status !== "failed") return false;
    if (filter === "cancelled" && r.status !== "cancelled") return false;
    if (filter === "active" && r.status !== "queued" && r.status !== "running") return false;
    if (search) {
      const q = search.toLowerCase();
      const matchId = `#${r.id}`.includes(q) || `${r.id}`.includes(q);
      const matchStatus = r.status?.toLowerCase().includes(q);
      const matchProject = r.project_name?.toLowerCase().includes(q);
      return matchId || matchStatus || matchProject;
    }
    return true;
  });

  const stats = {
    total: runs.length,
    completed: runs.filter((r) => r.status === "completed").length,
    failed: runs.filter((r) => r.status === "failed").length,
    cancelled: runs.filter((r) => r.status === "cancelled").length,
    active: runs.filter((r) => r.status === "queued" || r.status === "running").length,
  };

  const completedRuns = runs.filter((r) => r.status === "completed");
  const maxTests = Math.max(...completedRuns.map((r) => r.total_tests || 0), 1);

  return (
    <div className="page fade-in" style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* Header */}
      <div className="page-header" style={{ marginBottom: 18 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
              Test Run History
            </h1>
            {selectedProject && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: "var(--r-full)",
                  background: "var(--brand-surface)",
                  color: "var(--brand-primary)",
                  border: "1px solid var(--brand-border)",
                }}
              >
                📁 {selectedProject.project_name}
              </span>
            )}
          </div>
          <p className="page-sub">
            Audit historical test runs, track quality regressions, and load diagnostics.
            {stats.active > 0 && (
              <span style={{ color: "var(--brand-primary)", fontWeight: 700, marginLeft: 6 }}>
                &bull; {stats.active} background job{stats.active !== 1 ? "s" : ""} active
              </span>
            )}
          </p>
        </div>

        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={fetchRuns}
          disabled={loading}
          style={{ fontSize: 12 }}
        >
          {loading ? <div className="spinner" style={{ width: 12, height: 12 }} /> : "↻"} Refresh History
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div
        className="card"
        style={{
          marginBottom: 18,
          padding: "12px 18px",
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          background: "var(--bg-subtle)",
        }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {[
            { key: "all", label: `All (${stats.total})` },
            { key: "active", label: `Active (${stats.active})` },
            { key: "completed", label: `Completed (${stats.completed})` },
            { key: "failed", label: `Failed (${stats.failed})` },
            { key: "cancelled", label: `Cancelled (${stats.cancelled})` },
          ].map((f) => (
            <button
              key={f.key}
              type="button"
              className={`btn btn-sm ${filter === f.key ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setFilter(f.key)}
              style={{ fontSize: 11.5, padding: "4px 12px" }}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div style={{ position: "relative", flex: "0 1 240px" }}>
          <input
            type="text"
            className="input"
            placeholder="Search run ID or project…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ height: 32, fontSize: 12, width: "100%" }}
          />
        </div>
      </div>

      {loading ? (
        <div className="empty-page" style={{ padding: "60px 20px" }}>
          <div className="spinner" style={{ width: 24, height: 24 }} />
          <p style={{ marginTop: 12, color: "var(--text-muted)", fontSize: 13 }}>Loading execution logs…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-page" style={{ padding: "60px 20px" }}>
          <div className="empty-icon">📂</div>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)", marginBottom: 6 }}>
            No Matching Test Runs
          </h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, maxWidth: 360, margin: "0 auto" }}>
            {search || filter !== "all"
              ? "No recorded runs match the search query or status filter."
              : "No test executions found for this workspace. Run your first test suite from the Dashboard."}
          </p>
        </div>
      ) : (
        <>
          {/* Trend chart for completed runs */}
          {completedRuns.length > 0 && filter !== "active" && filter !== "failed" && (
            <div className="card" style={{ marginBottom: 20, padding: "18px 22px" }}>
              <div className="card-header" style={{ marginBottom: 12 }}>
                <span className="card-title">Pass / Fail Trend</span>
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  Last {Math.min(completedRuns.length, 10)} completed runs
                </span>
              </div>
              <div className="trend-chart" style={{ height: 85 }}>
                {completedRuns
                  .slice(0, 10)
                  .reverse()
                  .map((run, i) => {
                    const passH = maxTests > 0 ? ((run.passed_tests || 0) / maxTests) * 100 : 0;
                    const failH = maxTests > 0 ? ((run.failed_tests || 0) / maxTests) * 100 : 0;
                    return (
                      <div
                        key={run.id || i}
                        className="trend-col"
                        onClick={() => onLoadRun?.(run.id)}
                        title={`Run #${run.id}: ${run.passed_tests || 0} passed, ${run.failed_tests || 0} failed`}
                        style={{ cursor: "pointer" }}
                      >
                        <div className="trend-bars">
                          {failH > 0 && <div className="trend-bar rose" style={{ height: `${failH}%` }} />}
                          {passH > 0 && <div className="trend-bar green" style={{ height: `${passH}%` }} />}
                        </div>
                        <div className="trend-label">#{run.id}</div>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Runs table */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div className="history-table">
              <div className="history-th-row">
                <span>Run</span>
                <span>Project</span>
                <span>Status</span>
                <span>Date & Time</span>
                <span>Total</span>
                <span>Passed</span>
                <span>Failed</span>
                <span>Pass Rate</span>
                <span>Action</span>
              </div>
              {filtered.map((run) => {
                const rate =
                  run.total_tests > 0
                    ? ((run.passed_tests / run.total_tests) * 100).toFixed(1)
                    : 0;
                const isActive = run.status === "queued" || run.status === "running";
                const displayDate = run.created_at || run.started_at;

                return (
                  <div
                    key={run.id}
                    className="history-td-row"
                    onClick={() => {
                      if (isActive) {
                        onViewActiveRun?.(run.id);
                      } else if (run.status === "completed") {
                        onLoadRun?.(run.id);
                      }
                    }}
                    style={{ cursor: isActive || run.status === "completed" ? "pointer" : "default" }}
                  >
                    <span className="history-run-id">#{run.id}</span>
                    <span style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 600 }}>
                      {run.project_name || "Default Target"}
                    </span>
                    <span>
                      <StatusBadge status={run.status} />
                    </span>
                    <span className="history-date">
                      {displayDate ? new Date(displayDate).toLocaleString() : "—"}
                    </span>
                    <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
                      {run.status === "completed" ? (run.total_tests ?? "—") : "—"}
                    </span>
                    <span style={{ color: "var(--success)", fontWeight: 600 }}>
                      {run.status === "completed" ? `✓ ${run.passed_tests ?? 0}` : "—"}
                    </span>
                    <span style={{ color: "var(--danger)", fontWeight: 600 }}>
                      {run.status === "completed" ? `✗ ${run.failed_tests ?? 0}` : "—"}
                    </span>
                    <span>
                      {run.status === "completed" && run.total_tests > 0 ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div
                            style={{
                              flex: 1,
                              background: "rgba(255,255,255,0.06)",
                              borderRadius: 99,
                              height: 5,
                              overflow: "hidden",
                            }}
                          >
                            <div
                              style={{
                                height: "100%",
                                width: `${rate}%`,
                                background:
                                  rate >= 80
                                    ? "var(--success)"
                                    : rate >= 50
                                    ? "var(--warning)"
                                    : "var(--danger)",
                                borderRadius: 99,
                              }}
                            />
                          </div>
                          <span style={{ fontSize: 11.5, color: "var(--text-secondary)", minWidth: 36 }}>
                            {rate}%
                          </span>
                        </div>
                      ) : (
                        "—"
                      )}
                    </span>
                    <span>
                      {isActive ? (
                        <button
                          type="button"
                          className="shortcut-btn"
                          style={{ fontSize: 11 }}
                          onClick={(e) => {
                            e.stopPropagation();
                            onViewActiveRun?.(run.id);
                          }}
                        >
                          Monitor →
                        </button>
                      ) : run.status === "completed" ? (
                        <button
                          type="button"
                          className="shortcut-btn"
                          style={{ fontSize: 11 }}
                          onClick={(e) => {
                            e.stopPropagation();
                            onLoadRun?.(run.id);
                          }}
                        >
                          Load →
                        </button>
                      ) : run.status === "failed" && run.error_message ? (
                        <span
                          title={run.error_message}
                          style={{ fontSize: 11, color: "var(--danger)", cursor: "help" }}
                        >
                          ⚠ Error Details
                        </span>
                      ) : null}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
