import { useState, useEffect, useCallback } from "react";

export function AdminDashboard({ apiBaseUrl, token, currentUser, onNavigate }) {
  const [overview, setOverview] = useState(null);
  const [usersData, setUsersData] = useState({ total: 0, items: [] });
  const [usageTelemetry, setUsageTelemetry] = useState(null);

  // Users table controls
  const [page, setPage] = useState(0);
  const limit = 10;
  const [searchTerm, setSearchTerm] = useState("");
  const [activeSearch, setActiveSearch] = useState("");

  // User Inspection Modal
  const [inspectedUser, setInspectedUser] = useState(null);
  const [loadingInspection, setLoadingInspection] = useState(false);
  const [inspectionError, setInspectionError] = useState("");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const fetchAdminData = useCallback(async () => {
    if (!token) return;

    try {
      const headers = { Authorization: `Bearer ${token}` };

      const searchParam = activeSearch ? `&search=${encodeURIComponent(activeSearch)}` : "";
      const usersQs = `?limit=${limit}&offset=${page * limit}${searchParam}`;

      const [resOverview, resUsers, resUsage] = await Promise.all([
        fetch(`${apiBaseUrl}/admin/overview`, { headers }),
        fetch(`${apiBaseUrl}/admin/users${usersQs}`, { headers }),
        fetch(`${apiBaseUrl}/admin/usage`, { headers }),
      ]);

      if (!resOverview.ok || !resUsers.ok || !resUsage.ok) {
        if (resOverview.status === 403 || resUsers.status === 403) {
          throw new Error("Access Denied: You must be an administrator to view this portal.");
        }
        throw new Error("Failed to load administration telemetry.");
      }

      const [dataOverview, dataUsers, dataUsage] = await Promise.all([
        resOverview.json(),
        resUsers.json(),
        resUsage.json(),
      ]);

      setOverview(dataOverview);
      setUsersData(dataUsers);
      setUsageTelemetry(dataUsage);
      setError("");
    } catch (err) {
      setError(err.message || "Failed to load admin dashboard.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiBaseUrl, token, page, limit, activeSearch]);

  useEffect(() => {
    if (!token) return;
    let ignore = false;

    const run = async () => {
      try {
        const headers = { Authorization: `Bearer ${token}` };

        const searchParam = activeSearch ? `&search=${encodeURIComponent(activeSearch)}` : "";
        const usersQs = `?limit=${limit}&offset=${page * limit}${searchParam}`;

        const [resOverview, resUsers, resUsage] = await Promise.all([
          fetch(`${apiBaseUrl}/admin/overview`, { headers }),
          fetch(`${apiBaseUrl}/admin/users${usersQs}`, { headers }),
          fetch(`${apiBaseUrl}/admin/usage`, { headers }),
        ]);

        if (!resOverview.ok || !resUsers.ok || !resUsage.ok) {
          if (resOverview.status === 403 || resUsers.status === 403) {
            throw new Error("Access Denied: You must be an administrator to view this portal.");
          }
          throw new Error("Failed to load administration telemetry.");
        }

        const [dataOverview, dataUsers, dataUsage] = await Promise.all([
          resOverview.json(),
          resUsers.json(),
          resUsage.json(),
        ]);

        if (!ignore) {
          setOverview(dataOverview);
          setUsersData(dataUsers);
          setUsageTelemetry(dataUsage);
          setError("");
        }
      } catch (err) {
        if (!ignore) {
          setError(err.message || "Failed to load admin dashboard.");
        }
      } finally {
        if (!ignore) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    };

    run();

    return () => {
      ignore = true;
    };
  }, [apiBaseUrl, token, page, limit, activeSearch]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(0);
    setActiveSearch(searchTerm.trim());
  };

  const handleRefresh = () => {
    setRefreshing(true);
    fetchAdminData();
  };

  // Inspect user detail
  const handleInspectUser = async (userId) => {
    if (!token) return;
    setLoadingInspection(true);
    setInspectionError("");
    setInspectedUser(null);

    try {
      const res = await fetch(`${apiBaseUrl}/admin/users/${userId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        throw new Error("Failed to retrieve user profile telemetry.");
      }
      const data = await res.json();
      setInspectedUser(data);
    } catch (err) {
      setInspectionError(err.message || "Failed to inspect user.");
    } finally {
      setLoadingInspection(false);
    }
  };

  // Guard: if user is not admin
  if (currentUser?.role !== "admin") {
    return (
      <div className="page fade-in" style={{ padding: "60px 20px", textAlign: "center" }}>
        <div style={{ fontSize: 52, marginBottom: 16 }}>🛡️</div>
        <h2 style={{ color: "var(--danger)", marginBottom: 8, fontSize: 22, fontWeight: 800 }}>
          Access Restricted: Administrator Scope Required
        </h2>
        <p style={{ color: "var(--text-secondary)", maxWidth: 460, margin: "0 auto 24px", fontSize: 13.5, lineHeight: 1.6 }}>
          This portal is reserved strictly for authenticated platform administrators. Your current account role (<strong>{currentUser?.role || "user"}</strong>) does not have administrative privileges.
        </p>
        <button className="btn btn-primary" onClick={() => onNavigate && onNavigate("dashboard")}>
          ← Return to Dashboard
        </button>
      </div>
    );
  }

  return (
    <div className="page fade-in" style={{ paddingBottom: 60 }}>
      {/* ── Page Header & Controls ── */}
      <div
        className="page-header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
              Platform Administration & Governance
            </h1>
            <span
              style={{
                fontSize: 10.5,
                fontWeight: 700,
                letterSpacing: 0.8,
                padding: "3px 8px",
                borderRadius: "var(--r-xs)",
                background: "var(--brand-surface)",
                border: "1px solid var(--brand-border)",
                color: "var(--brand-primary)",
                textTransform: "uppercase",
              }}
            >
              Mode: {overview?.platform_mode?.toUpperCase() || "INTERNAL"}
            </span>
            <span
              style={{
                fontSize: 10.5,
                fontWeight: 700,
                letterSpacing: 0.8,
                padding: "3px 8px",
                borderRadius: "var(--r-xs)",
                background: overview?.enforce_usage_limits ? "var(--warning-surface)" : "var(--success-surface)",
                border: `1px solid ${overview?.enforce_usage_limits ? "var(--warning-border)" : "var(--success-border)"}`,
                color: overview?.enforce_usage_limits ? "var(--warning)" : "var(--success)",
                textTransform: "uppercase",
              }}
            >
              Quota Enforcement: {overview?.enforce_usage_limits ? "Active" : "Disabled (Internal Demo)"}
            </span>
          </div>
          <p className="page-sub">
            Platform-wide telemetry, multi-tenant directory, AI operation audits, and tier capacity
          </p>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button
            className="btn btn-ghost"
            onClick={handleRefresh}
            disabled={refreshing || loading}
            style={{ display: "flex", alignItems: "center", gap: 6, height: 34, fontSize: 12 }}
          >
            <span
              style={{
                display: "inline-block",
                transform: refreshing ? "rotate(360deg)" : "none",
                transition: "transform 0.6s ease",
              }}
            >
              ↻
            </span>
            <span>{refreshing ? "Refreshing..." : "Refresh Telemetry"}</span>
          </button>
        </div>
      </div>

      {/* ── Error Banner ── */}
      {error && (
        <div
          style={{
            padding: "12px 16px",
            marginBottom: 20,
            borderRadius: "var(--r-sm)",
            background: "var(--danger-surface)",
            border: "1px solid var(--danger-border)",
            color: "var(--danger)",
            fontSize: 13,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span>⚠️</span>
            <span>{error}</span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={handleRefresh}>
            Retry
          </button>
        </div>
      )}

      {/* ── Platform KPI Cards Grid ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        {/* Total Users */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Registered Users
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--accent-cyan)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {overview?.total_users ?? 0}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Tenant accounts in MySQL
          </div>
        </div>

        {/* Active Users */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Active Users (30D)
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--success)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {overview?.active_users ?? 0}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Ran tests in last 30 days
          </div>
        </div>

        {/* Total Projects */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Total Projects
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--brand-primary)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {overview?.total_projects ?? 0}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Platform-wide endpoints
          </div>
        </div>

        {/* Total Test Runs */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Platform Runs
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--text-primary)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {overview?.total_test_runs ?? 0}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Test suites executed
          </div>
        </div>

        {/* Total Test Cases */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Total Test Cases
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--text-primary)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {(overview?.total_test_cases ?? 0).toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Endpoints verified
          </div>
        </div>

        {/* Platform Pass Rate */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Platform Pass Rate
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--success)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {overview?.overall_pass_percentage ?? 0}%
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            ✓ {overview?.total_passed_tests ?? 0} / ✗ {overview?.total_failed_tests ?? 0}
          </div>
        </div>
      </div>

      {/* ── User Directory Table ── */}
      <div className="card" style={{ padding: 22, marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
          <div>
            <span className="card-title" style={{ fontSize: 14, fontWeight: 700 }}>
              Multi-Tenant User Directory
            </span>
            <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
              Account telemetry, role permissions, active plans, and usage counters
            </p>
          </div>

          {/* Search form */}
          <form onSubmit={handleSearchSubmit} style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              className="input"
              placeholder="Search by email or name..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ width: 230, height: 32, fontSize: 12, padding: "4px 10px" }}
            />
            <button type="submit" className="btn btn-primary" style={{ height: 32, padding: "0 12px", fontSize: 12 }}>
              Search
            </button>
            {activeSearch && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setSearchTerm("");
                  setActiveSearch("");
                  setPage(0);
                }}
                style={{ height: 32, padding: "0 8px", fontSize: 12 }}
              >
                Clear
              </button>
            )}
          </form>
        </div>

        {usersData.items && usersData.items.length > 0 ? (
          <>
            <div className="history-table" style={{ overflowX: "auto" }}>
              <div
                className="history-th-row"
                style={{
                  gridTemplateColumns: "60px 1.2fr 1.5fr 80px 100px 70px 70px 110px 90px",
                  borderBottom: "1px solid var(--border-default)",
                }}
              >
                <span>ID</span>
                <span>Name</span>
                <span>Email</span>
                <span>Role</span>
                <span>Plan</span>
                <span>Projects</span>
                <span>Runs</span>
                <span>Last Active</span>
                <span style={{ textAlign: "right" }}>Inspect</span>
              </div>

              {usersData.items.map((u) => (
                <div
                  key={u.id}
                  className="history-td-row"
                  style={{
                    gridTemplateColumns: "60px 1.2fr 1.5fr 80px 100px 70px 70px 110px 90px",
                  }}
                >
                  <span className="history-run-id">#{u.id}</span>
                  <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{u.full_name}</span>
                  <span style={{ color: "var(--text-secondary)", fontFamily: "var(--mono)", fontSize: 11.5 }}>{u.email}</span>
                  <span>
                    <span
                      style={{
                        padding: "2px 8px",
                        borderRadius: "var(--r-xs)",
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: 0.5,
                        background: u.role === "admin" ? "var(--brand-surface)" : "var(--bg-subtle)",
                        color: u.role === "admin" ? "var(--brand-primary)" : "var(--text-secondary)",
                        border: u.role === "admin" ? "1px solid var(--brand-border)" : "1px solid var(--border-subtle)",
                      }}
                    >
                      {u.role}
                    </span>
                  </span>
                  <span>
                    <span
                      style={{
                        padding: "2px 8px",
                        borderRadius: "var(--r-xs)",
                        fontSize: 10.5,
                        fontWeight: 600,
                        background: "rgba(6,182,212,0.12)",
                        color: "var(--accent-cyan)",
                        border: "1px solid rgba(6,182,212,0.25)",
                      }}
                    >
                      {u.plan}
                    </span>
                  </span>
                  <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{u.project_count}</span>
                  <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{u.test_run_count}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {u.last_activity ? new Date(u.last_activity).toLocaleDateString() : "Never"}
                  </span>
                  <span style={{ textAlign: "right" }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ fontSize: 11, padding: "2px 8px" }}
                      onClick={() => handleInspectUser(u.id)}
                    >
                      Inspect →
                    </button>
                  </span>
                </div>
              ))}
            </div>

            {/* Pagination */}
            {usersData.total > limit && (
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginTop: 16,
                  paddingTop: 12,
                  borderTop: "1px solid var(--border-subtle)",
                }}
              >
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  style={{ fontSize: 12 }}
                >
                  ← Previous
                </button>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Page {page + 1} of {Math.ceil(usersData.total / limit)} ({usersData.total} users)
                </span>
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={(page + 1) * limit >= usersData.total}
                  onClick={() => setPage((p) => p + 1)}
                  style={{ fontSize: 12 }}
                >
                  Next →
                </button>
              </div>
            )}
          </>
        ) : (
          <div style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            No users found matching your search term.
          </div>
        )}
      </div>

      {/* ── Two-Column Row: Platform Activity & Monetization Architecture ── */}
      <div className="grid-admin-2col">
        {/* Recent Platform Executions */}
        <div className="card" style={{ padding: 22 }}>
          <span className="card-title" style={{ fontSize: 14, fontWeight: 700 }}>
            Recent Platform Test Executions
          </span>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 14px" }}>
            Cross-tenant test execution telemetry stream
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {overview?.recent_activity && overview.recent_activity.length > 0 ? (
              overview.recent_activity.map((run) => (
                <div
                  key={run.run_id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "9px 12px",
                    borderRadius: "var(--r-sm)",
                    background: "var(--bg-subtle)",
                    border: "1px solid var(--border-subtle)",
                    fontSize: 12,
                  }}
                >
                  <div>
                    <span style={{ color: "var(--brand-primary)", fontWeight: 700, fontFamily: "var(--mono)" }}>
                      #{run.run_id}
                    </span>{" "}
                    • <strong style={{ color: "var(--text-primary)" }}>{run.project_name}</strong>{" "}
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>(Tenant #{run.user_id})</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span
                      style={{
                        padding: "1px 6px",
                        borderRadius: 3,
                        fontSize: 10.5,
                        fontWeight: 700,
                        background: run.status === "PASS" ? "var(--success-surface)" : "var(--danger-surface)",
                        color: run.status === "PASS" ? "var(--success)" : "var(--danger)",
                      }}
                    >
                      {run.status}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {run.created_at ? new Date(run.created_at).toLocaleTimeString() : "—"}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: 12 }}>No execution activity recorded.</div>
            )}
          </div>
        </div>

        {/* Monetization-Ready Plan Architecture */}
        <div className="card" style={{ padding: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="card-title" style={{ fontSize: 14, fontWeight: 700 }}>
              Monetization Architecture & Quotas
            </span>
            {usageTelemetry?.total_ai_operations !== undefined && (
              <span
                style={{
                  fontSize: 11,
                  padding: "2px 8px",
                  borderRadius: "var(--r-xs)",
                  background: "rgba(139,92,246,0.15)",
                  color: "#8b5cf6",
                  fontWeight: 700,
                  fontFamily: "var(--mono)",
                }}
              >
                AI Ops: {usageTelemetry.total_ai_operations}
              </span>
            )}
          </div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 14px" }}>
            Tier definitions, feature entitlements, and active tenant distribution
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {usageTelemetry?.available_plans &&
              Object.entries(usageTelemetry.available_plans).map(([key, plan]) => {
                const isInternal = key === "internal_demo";
                const userCount = usageTelemetry?.plan_distribution?.[key] || 0;
                return (
                  <div
                    key={key}
                    style={{
                      padding: "10px 14px",
                      borderRadius: "var(--r-sm)",
                      background: isInternal ? "var(--brand-surface)" : "var(--bg-subtle)",
                      border: `1px solid ${isInternal ? "var(--brand-border)" : "var(--border-subtle)"}`,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                      <strong style={{ fontSize: 12.5, color: isInternal ? "var(--brand-primary)" : "var(--text-primary)" }}>
                        {plan.name}
                      </strong>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          color: userCount > 0 ? "var(--text-primary)" : "var(--text-muted)",
                        }}
                      >
                        {userCount} tenant{userCount !== 1 ? "s" : ""}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                      Allowance: {plan.max_projects} Projects • {plan.monthly_test_runs} Runs/mo • {plan.monthly_ai_operations} AI Ops/mo
                    </div>
                  </div>
                );
              })}
          </div>

          <div
            style={{
              marginTop: 14,
              padding: "8px 12px",
              borderRadius: "var(--r-xs)",
              background: "var(--bg-subtle)",
              border: "1px solid var(--border-subtle)",
              fontSize: 11,
              color: "var(--text-muted)",
              lineHeight: 1.5,
            }}
          >
            <strong>Governance Policy:</strong> Platform currently operates in internal demo mode. Hard quota enforcement is off by default (<code style={{ fontFamily: "var(--mono)", fontSize: 10 }}>ENFORCE_USAGE_LIMITS=false</code>).
          </div>
        </div>
      </div>

      {/* ── User Inspection Modal ── */}
      {(inspectedUser || loadingInspection || inspectionError) && (
        <div className="modal-backdrop fade-in" onClick={() => !loadingInspection && setInspectedUser(null)}>
          <div
            className="modal-content"
            style={{ maxWidth: 620, padding: 24 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 20 }}>👤</span>
                <div>
                  <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                    Tenant Inspection: #{inspectedUser?.user?.id || ""} {inspectedUser?.user?.full_name || ""}
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--mono)" }}>
                    {inspectedUser?.user?.email || ""}
                  </p>
                </div>
              </div>
              <button className="icon-btn" onClick={() => setInspectedUser(null)}>
                ✕
              </button>
            </div>

            {loadingInspection ? (
              <div style={{ padding: "40px 0", textAlign: "center", color: "var(--text-muted)" }}>
                Loading user telemetry...
              </div>
            ) : inspectionError ? (
              <div style={{ padding: "16px", color: "var(--danger)", background: "var(--danger-surface)", borderRadius: "var(--r-sm)" }}>
                {inspectionError}
              </div>
            ) : inspectedUser ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {/* User Stats Grid */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                  <div style={{ padding: "10px 12px", background: "var(--bg-subtle)", borderRadius: "var(--r-sm)" }}>
                    <div style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase" }}>Plan Tier</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "var(--accent-cyan)", marginTop: 2 }}>
                      {inspectedUser.user.plan}
                    </div>
                  </div>
                  <div style={{ padding: "10px 12px", background: "var(--bg-subtle)", borderRadius: "var(--r-sm)" }}>
                    <div style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase" }}>Test Runs</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", marginTop: 2, fontFamily: "var(--mono)" }}>
                      {inspectedUser.usage.total_runs}
                    </div>
                  </div>
                  <div style={{ padding: "10px 12px", background: "var(--bg-subtle)", borderRadius: "var(--r-sm)" }}>
                    <div style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase" }}>Pass Rate</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "var(--success)", marginTop: 2, fontFamily: "var(--mono)" }}>
                      {inspectedUser.usage.pass_percentage}%
                    </div>
                  </div>
                </div>

                {/* Projects list */}
                <div>
                  <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                    Configured Projects ({inspectedUser.projects?.length || 0})
                  </h4>
                  {inspectedUser.projects && inspectedUser.projects.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 180, overflowY: "auto" }}>
                      {inspectedUser.projects.map((proj) => (
                        <div
                          key={proj.id}
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            padding: "6px 10px",
                            background: "var(--bg-subtle)",
                            borderRadius: "var(--r-xs)",
                            fontSize: 11.5,
                          }}
                        >
                          <div>
                            <strong style={{ color: "var(--text-primary)" }}>{proj.project_name}</strong>
                            <span style={{ color: "var(--text-muted)", marginLeft: 8, fontFamily: "var(--mono)" }}>
                              {proj.base_url}
                            </span>
                          </div>
                          <span style={{ color: "var(--text-secondary)", fontFamily: "var(--mono)" }}>
                            {proj.run_count} runs
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={{ color: "var(--text-muted)", fontSize: 12 }}>No projects configured yet.</div>
                  )}
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                  <button className="btn btn-ghost" onClick={() => setInspectedUser(null)}>
                    Close
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
