import { useState, useEffect, useRef, useCallback } from "react";

/**
 * RunProgress — Live background test execution monitor.
 * Displays real-time status, project, elapsed time, animated progress bar,
 * pass/fail metrics, error messages, and cancellation control.
 */

const STATUS_CONFIG = {
  queued:    { label: "Queued",     color: "var(--warning)",  icon: "⏳", animate: true  },
  running:  { label: "Running",    color: "var(--brand-primary)", icon: "⚙️", animate: true  },
  completed:{ label: "Completed",  color: "var(--success)",  icon: "✓",  animate: false },
  failed:   { label: "Failed",     color: "var(--danger)",   icon: "✗",  animate: false },
  cancelled:{ label: "Cancelled",  color: "var(--text-muted)", icon: "⊘", animate: false },
};

const POLL_INTERVAL = 2500;

function formatElapsed(startIso) {
  if (!startIso) return "—";
  const start = new Date(startIso);
  const now = new Date();
  const diff = Math.max(0, Math.floor((now - start) / 1000));
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function RunProgress({
  runId,
  activeRun,
  projectName,
  apiBaseUrl,
  token,
  onComplete,
  onCancel,
  onError,
  onNavigate,
}) {
  const [internalRun, setInternalRun] = useState(activeRun || null);
  const [cancelling, setCancelling] = useState(false);
  const [elapsed, setElapsed] = useState("—");
  const pollRef = useRef(null);
  const elapsedRef = useRef(null);

  // Sync with activeRun prop when updated by parent
  useEffect(() => {
    if (activeRun) {
      setInternalRun((prev) => ({ ...prev, ...activeRun }));
    }
  }, [activeRun]);

  const targetRunId = runId || activeRun?.id || internalRun?.id;

  const fetchStatus = useCallback(async () => {
    if (!targetRunId || !apiBaseUrl) return;
    try {
      const res = await fetch(`${apiBaseUrl}/test-runs/${targetRunId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.status === 401) {
        onError?.("Session expired. Please sign in again.");
        return;
      }
      if (!res.ok) {
        const text = await res.text();
        onError?.(text || "Failed to fetch run status.");
        return;
      }
      const json = await res.json();
      const data = json.data;
      setInternalRun(data);

      // Terminal states — stop polling and trigger completion
      if (data.status === "completed") {
        clearInterval(pollRef.current);
        clearInterval(elapsedRef.current);
        onComplete?.(data);
      } else if (data.status === "failed" || data.status === "cancelled") {
        clearInterval(pollRef.current);
        clearInterval(elapsedRef.current);
      }
    } catch {
      // Network failure — keep existing state and retry on next interval
    }
  }, [targetRunId, apiBaseUrl, token, onComplete, onError]);

  // Polling management: only poll if status is queued or running
  useEffect(() => {
    if (!targetRunId) return;

    fetchStatus();
    pollRef.current = setInterval(fetchStatus, POLL_INTERVAL);

    return () => {
      clearInterval(pollRef.current);
      clearInterval(elapsedRef.current);
    };
  }, [targetRunId, fetchStatus]);

  // Real-time elapsed timer
  useEffect(() => {
    const run = internalRun;
    if (run?.started_at && (run.status === "running" || run.status === "queued")) {
      const tick = () => setElapsed(formatElapsed(run.started_at || run.created_at));
      tick();
      elapsedRef.current = setInterval(tick, 1000);
      return () => clearInterval(elapsedRef.current);
    }
    if (run?.status === "completed" && run.started_at && run.completed_at) {
      const start = new Date(run.started_at);
      const end = new Date(run.completed_at);
      const diff = Math.max(0, Math.floor((end - start) / 1000));
      const m = Math.floor(diff / 60);
      const s = diff % 60;
      setElapsed(m > 0 ? `${m}m ${s}s` : `${s}s`);
    } else if (run?.created_at && run.status === "queued") {
      const tick = () => setElapsed(formatElapsed(run.created_at));
      tick();
      elapsedRef.current = setInterval(tick, 1000);
      return () => clearInterval(elapsedRef.current);
    }
  }, [internalRun?.started_at, internalRun?.completed_at, internalRun?.status, internalRun?.created_at]);

  const handleCancel = async () => {
    if (cancelling || !targetRunId) return;
    setCancelling(true);
    try {
      const res = await fetch(`${apiBaseUrl}/test-runs/${targetRunId}/cancel`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        setInternalRun((prev) => prev ? { ...prev, status: "cancelled" } : prev);
        clearInterval(pollRef.current);
        clearInterval(elapsedRef.current);
        onCancel?.(targetRunId);
      } else {
        const text = await res.text();
        onError?.(text || "Failed to cancel run.");
      }
    } catch {
      onError?.("Network error while cancelling run.");
    } finally {
      setCancelling(false);
    }
  };

  const run = internalRun;
  const cfg = STATUS_CONFIG[run?.status] || STATUS_CONFIG.queued;
  const isActive = run?.status === "queued" || run?.status === "running";
  const total = run?.total_tests || run?.estimated_tests || 0;
  const passed = run?.passed_tests || 0;
  const failed = run?.failed_tests || 0;
  const done = passed + failed;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const displayProject = projectName || run?.project_name;

  return (
    <div
      className="card fade-in"
      style={{
        padding: "20px 24px",
        marginBottom: 20,
        background: isActive
          ? "linear-gradient(135deg, var(--brand-surface) 0%, var(--bg-surface) 100%)"
          : "var(--bg-surface)",
        border: isActive
          ? "1px solid var(--brand-border)"
          : "1px solid var(--border-default)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: "var(--r-sm)",
              background: cfg.animate ? "var(--brand-surface)" : "var(--bg-subtle)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 18,
              border: `1px solid ${cfg.color}`,
              color: cfg.color,
            }}
          >
            {cfg.icon}
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                Test Run #{targetRunId}
              </h3>
              {displayProject && (
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    padding: "2px 8px",
                    borderRadius: "var(--r-full)",
                    background: "var(--bg-subtle)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border-default)",
                  }}
                >
                  📁 {displayProject}
                </span>
              )}
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: "var(--r-full)",
                  background: cfg.color + "18",
                  color: cfg.color,
                  border: `1px solid ${cfg.color}40`,
                  textTransform: "uppercase",
                }}
              >
                {cfg.label}
              </span>
            </div>
            <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-secondary)" }}>
              {run?.created_at && (
                <>Submitted: {new Date(run.created_at).toLocaleTimeString()}</>
              )}
              {run?.started_at && (
                <> &bull; Started: {new Date(run.started_at).toLocaleTimeString()}</>
              )}
              {run?.completed_at && (
                <> &bull; Finished: {new Date(run.completed_at).toLocaleTimeString()}</>
              )}
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {isActive && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={handleCancel}
              disabled={cancelling}
              style={{
                fontSize: 12,
                color: "var(--danger)",
                borderColor: "var(--danger-border, rgba(244,63,94,0.3))",
              }}
            >
              {cancelling ? (
                <>
                  <div className="spinner" style={{ width: 12, height: 12 }} />
                  Cancelling…
                </>
              ) : (
                <>✕ Cancel Run</>
              )}
            </button>
          )}

          {run?.status === "completed" && (
            <>
              <button
                type="button"
                className="shortcut-btn"
                onClick={() => onNavigate?.("results")}
                style={{ fontSize: 11.5 }}
              >
                View Results →
              </button>
              <button
                type="button"
                className="shortcut-btn rose"
                onClick={() => onNavigate?.("bugs")}
                style={{ fontSize: 11.5 }}
              >
                View Bugs ({failed}) →
              </button>
            </>
          )}
        </div>
      </div>

      {/* Progress bar & Stage status */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--text-secondary)", marginBottom: 6 }}>
          <span>
            {run?.status === "queued" ? "Waiting for background worker slot…" :
             run?.status === "running" ? (total > 0 ? `Executing test suite (${done} / ${total})` : "Worker claimed job & executing tests…") :
             run?.status === "completed" ? `Execution complete · ${total} tests executed` :
             run?.status === "failed" ? "Execution failed" :
             run?.status === "cancelled" ? "Job execution cancelled" : "Initializing…"}
          </span>
          <span style={{ fontFamily: "var(--mono)", fontWeight: 600 }}>
            {isActive ? `Elapsed: ${elapsed}` : (run?.status === "completed" ? `Duration: ${elapsed}` : "")}
          </span>
        </div>

        <div className="progress-bar-wrap" style={{ height: 7, margin: 0 }}>
          <div
            className={`progress-bar-fill ${
              isActive && (run?.status === "queued" || !total || done === 0)
                ? "progress-bar-indeterminate"
                : cfg.animate
                ? "progress-animated"
                : ""
            }`}
            style={{
              width:
                run?.status === "completed"
                  ? "100%"
                  : isActive && (run?.status === "queued" || !total || done === 0)
                  ? "100%"
                  : total > 0
                  ? `${pct}%`
                  : "100%",
              background:
                run?.status === "completed"
                  ? "var(--success)"
                  : run?.status === "failed"
                  ? "var(--danger)"
                  : run?.status === "cancelled"
                  ? "var(--text-muted)"
                  : isActive && (run?.status === "queued" || !total || done === 0)
                  ? undefined
                  : "linear-gradient(90deg, var(--brand-primary), #06b6d4)",
              transition: "width 0.4s ease",
            }}
          />
        </div>
      </div>

      {/* Metric counters for completed or active test results */}
      {total > 0 && (run?.status === "running" || run?.status === "completed") && (
        <div style={{ display: "flex", gap: 20, fontSize: 12, flexWrap: "wrap", paddingTop: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#3b82f6" }} />
            <span style={{ color: "var(--text-secondary)" }}>Total:</span>
            <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{total}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#10b981" }} />
            <span style={{ color: "var(--text-secondary)" }}>Passed:</span>
            <span style={{ fontWeight: 700, color: "var(--success)" }}>{passed}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#f43f5e" }} />
            <span style={{ color: "var(--text-secondary)" }}>Failed:</span>
            <span style={{ fontWeight: 700, color: "var(--danger)" }}>{failed}</span>
          </div>
          {run?.pass_rate != null && run.status === "completed" && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
              <span style={{ color: "var(--text-secondary)" }}>Pass Rate:</span>
              <span style={{ fontWeight: 800, color: "var(--brand-primary)" }}>{run.pass_rate}%</span>
            </div>
          )}
        </div>
      )}

      {/* Error message banner */}
      {run?.status === "failed" && run.error_message && (
        <div
          style={{
            marginTop: 12,
            padding: "10px 14px",
            borderRadius: "var(--r-sm)",
            background: "var(--danger-surface)",
            border: "1px solid var(--danger-border)",
            fontSize: 12,
            color: "var(--danger)",
            fontFamily: "var(--mono)",
            wordBreak: "break-word",
          }}
        >
          <strong>Failure Diagnostic:</strong> {run.error_message}
        </div>
      )}
    </div>
  );
}
