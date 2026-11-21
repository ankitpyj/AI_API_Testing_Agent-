import { useState, useEffect, useCallback, useMemo } from "react";

export function AnalyticsPage({ apiBaseUrl, token, projects: initialProjects = [], onViewRun }) {
  // Filter states
  const [projects, setProjects] = useState(initialProjects);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedDays, setSelectedDays] = useState(7);
  const [customRange, setCustomRange] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Load projects if not supplied
  useEffect(() => {
    if (!token) return;
    fetch(`${apiBaseUrl}/projects`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : { data: [] }))
      .then((json) => setProjects(json.data || []))
      .catch(() => {});
  }, [apiBaseUrl, token]);

  // Data states
  const [overview, setOverview] = useState(null);
  const [trends, setTrends] = useState([]);
  const [projectPerformance, setProjectPerformance] = useState([]);
  const [bugSummary, setBugSummary] = useState(null);
  const [recentActivity, setRecentActivity] = useState({ total: 0, items: [] });

  // Pagination for recent activity
  const [activityPage, setActivityPage] = useState(0);
  const activityLimit = 8;

  // UI state
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [hoveredTrend, setHoveredTrend] = useState(null);

  // Build query string helper
  const buildQuery = useCallback(
    (extraParams = {}) => {
      const params = new URLSearchParams();
      if (selectedProjectId) {
        params.append("project_id", selectedProjectId);
      }
      if (customRange && startDate) {
        params.append("start_date", startDate);
      }
      if (customRange && endDate) {
        params.append("end_date", endDate);
      }
      if (!customRange && selectedDays) {
        params.append("days", selectedDays);
      }
      Object.entries(extraParams).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") {
          params.append(k, v);
        }
      });
      const qs = params.toString();
      return qs ? `?${qs}` : "";
    },
    [selectedProjectId, customRange, startDate, endDate, selectedDays]
  );

  // Fetch all analytics in parallel
  const fetchAllAnalytics = useCallback(async () => {
    if (!token) return;

    try {
      const headers = { Authorization: `Bearer ${token}` };
      const qs = buildQuery();

      const [resOverview, resTrends, resPerformance, resBugs, resActivity] =
        await Promise.all([
          fetch(`${apiBaseUrl}/analytics/overview${qs}`, { headers }),
          fetch(`${apiBaseUrl}/analytics/test-trends${qs}`, { headers }),
          fetch(`${apiBaseUrl}/analytics/project-performance${qs}`, { headers }),
          fetch(`${apiBaseUrl}/analytics/bug-summary${qs}`, { headers }),
          fetch(
            `${apiBaseUrl}/analytics/recent-activity${buildQuery({
              limit: activityLimit,
              offset: activityPage * activityLimit,
            })}`,
            { headers }
          ),
        ]);

      if (
        !resOverview.ok ||
        !resTrends.ok ||
        !resPerformance.ok ||
        !resBugs.ok ||
        !resActivity.ok
      ) {
        const errJson = await (resOverview.ok ? resTrends : resOverview)
          .json()
          .catch(() => ({}));
        throw new Error(errJson.detail || "Failed to load analytics data.");
      }

      const [dataOverview, dataTrends, dataPerf, dataBugs, dataActivity] =
        await Promise.all([
          resOverview.json(),
          resTrends.json(),
          resPerformance.json(),
          resBugs.json(),
          resActivity.json(),
        ]);

      setOverview(dataOverview);
      setTrends(dataTrends.trends || []);
      setProjectPerformance(dataPerf.projects || []);
      setBugSummary(dataBugs);
      setRecentActivity(dataActivity);
      setError("");
    } catch (err) {
      setError(err.message || "Network error loading analytics.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiBaseUrl, token, buildQuery, activityPage, activityLimit]);

  // Initial load and filter/page changes
  useEffect(() => {
    if (!token) return;
    let ignore = false;

    const run = async () => {
      try {
        const headers = { Authorization: `Bearer ${token}` };
        const qs = buildQuery();

        const [resOverview, resTrends, resPerformance, resBugs, resActivity] =
          await Promise.all([
            fetch(`${apiBaseUrl}/analytics/overview${qs}`, { headers }),
            fetch(`${apiBaseUrl}/analytics/test-trends${qs}`, { headers }),
            fetch(`${apiBaseUrl}/analytics/project-performance${qs}`, { headers }),
            fetch(`${apiBaseUrl}/analytics/bug-summary${qs}`, { headers }),
            fetch(
              `${apiBaseUrl}/analytics/recent-activity${buildQuery({
                limit: activityLimit,
                offset: activityPage * activityLimit,
              })}`,
              { headers }
            ),
          ]);

        if (
          !resOverview.ok ||
          !resTrends.ok ||
          !resPerformance.ok ||
          !resBugs.ok ||
          !resActivity.ok
        ) {
          const errJson = await (resOverview.ok ? resTrends : resOverview)
            .json()
            .catch(() => ({}));
          throw new Error(errJson.detail || "Failed to load analytics data.");
        }

        const [dataOverview, dataTrends, dataPerf, dataBugs, dataActivity] =
          await Promise.all([
            resOverview.json(),
            resTrends.json(),
            resPerformance.json(),
            resBugs.json(),
            resActivity.json(),
          ]);

        if (!ignore) {
          setOverview(dataOverview);
          setTrends(dataTrends.trends || []);
          setProjectPerformance(dataPerf.projects || []);
          setBugSummary(dataBugs);
          setRecentActivity(dataActivity);
          setError("");
        }
      } catch (err) {
        if (!ignore) {
          setError(err.message || "Network error loading analytics.");
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
  }, [apiBaseUrl, token, buildQuery, activityPage, activityLimit]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchAllAnalytics();
  };

  // Safe KPI values
  const totalProjects = overview?.total_projects ?? 0;
  const totalTestRuns = overview?.total_test_runs ?? 0;
  const totalTestCases = overview?.total_test_cases ?? 0;
  const totalPassed = overview?.total_passed_tests ?? 0;
  const totalFailed = overview?.total_failed_tests ?? 0;
  const passPercentage = overview?.pass_percentage ?? 0;
  const openBugs = overview?.open_bug_reports ?? 0;
  const totalBugs = overview?.total_bug_reports ?? 0;

  // ─────────────────────────────────────────────────────────────
  // SVG Chart 1: Test Trends Line & Area Chart
  // ─────────────────────────────────────────────────────────────
  const trendSvg = useMemo(() => {
    if (!trends || trends.length === 0) return null;

    const width = 640;
    const height = 190;
    const padding = { top: 20, right: 20, bottom: 30, left: 35 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    const maxTests = Math.max(...trends.map((t) => t.total_tests), 5);

    const points = trends.map((item, index) => {
      const x =
        padding.left +
        (trends.length > 1 ? (index / (trends.length - 1)) * chartW : chartW / 2);
      const y =
        padding.top +
        chartH -
        (maxTests > 0 ? (item.total_tests / maxTests) * chartH : 0);
      const yPassed =
        padding.top +
        chartH -
        (maxTests > 0 ? (item.passed_tests / maxTests) * chartH : 0);
      return { x, y, yPassed, item };
    });

    const linePath = points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join(" ");

    const areaPath =
      points.length > 0
        ? `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${(
            padding.top + chartH
          ).toFixed(1)} L ${points[0].x.toFixed(1)} ${(
            padding.top + chartH
          ).toFixed(1)} Z`
        : "";

    const passedLinePath = points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.yPassed.toFixed(1)}`)
      .join(" ");

    return { width, height, padding, chartW, chartH, points, linePath, areaPath, passedLinePath, maxTests };
  }, [trends]);

  // ─────────────────────────────────────────────────────────────
  // SVG Chart 2: Donut Chart (Pass vs Fail)
  // ─────────────────────────────────────────────────────────────
  const donutSvg = useMemo(() => {
    const total = totalPassed + totalFailed;
    if (total === 0) return null;

    const size = 160;
    const strokeWidth = 18;
    const radius = (size - strokeWidth) / 2;
    const center = size / 2;
    const circumference = 2 * Math.PI * radius;

    const passFraction = totalPassed / total;
    const passDash = passFraction * circumference;
    const failDash = (totalFailed / total) * circumference;

    return {
      size,
      strokeWidth,
      radius,
      center,
      circumference,
      passDash,
      failDash,
      passOffset: 0,
      failOffset: -passDash,
    };
  }, [totalPassed, totalFailed]);

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
          <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
            Analytics & Quality Intelligence
          </h1>
          <p className="page-sub">
            Real-time test suite metrics, reliability trends, and defect diagnostics
          </p>
        </div>

        {/* Global Controls */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {/* Project Selector */}
          <select
            className="input"
            value={selectedProjectId}
            onChange={(e) => {
              setSelectedProjectId(e.target.value);
              setActivityPage(0);
            }}
            style={{ height: 34, fontSize: 12.5, minWidth: 160, padding: "4px 10px" }}
          >
            <option value="">All Projects ({projects.length})</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.project_name}
              </option>
            ))}
          </select>

          {/* Timeframe Presets */}
          <div className="filter-tabs" style={{ background: "var(--bg-subtle)", padding: 3 }}>
            {[7, 14, 30, 90].map((d) => (
              <button
                key={d}
                type="button"
                className={`filter-tab ${!customRange && selectedDays === d ? "active" : ""}`}
                onClick={() => {
                  setCustomRange(false);
                  setSelectedDays(d);
                  setActivityPage(0);
                }}
                style={{ padding: "4px 10px", fontSize: 11.5 }}
              >
                {d}D
              </button>
            ))}
            <button
              type="button"
              className={`filter-tab ${customRange ? "active" : ""}`}
              onClick={() => {
                setCustomRange(!customRange);
                setActivityPage(0);
              }}
              style={{ padding: "4px 10px", fontSize: 11.5 }}
            >
              Custom
            </button>
          </div>

          {/* Custom Date Inputs */}
          {customRange && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input
                type="date"
                className="input"
                value={startDate}
                onChange={(e) => {
                  setStartDate(e.target.value);
                  setActivityPage(0);
                }}
                style={{ height: 34, fontSize: 12, width: 135, padding: "2px 6px" }}
              />
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>to</span>
              <input
                type="date"
                className="input"
                value={endDate}
                onChange={(e) => {
                  setEndDate(e.target.value);
                  setActivityPage(0);
                }}
                style={{ height: 34, fontSize: 12, width: 135, padding: "2px 6px" }}
              />
            </div>
          )}

          {/* Refresh Button */}
          <button
            className="btn btn-ghost"
            onClick={handleRefresh}
            disabled={refreshing || loading}
            style={{ height: 34, padding: "0 12px", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}
            title="Refresh analytics data"
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
            <span>{refreshing ? "Refreshing..." : "Refresh"}</span>
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

      {/* ── Scope & Tenant Isolation Summary Banner ── */}
      {overview?.usage && (
        <div
          style={{
            padding: "10px 18px",
            marginBottom: 20,
            borderRadius: "var(--r-sm)",
            background: "var(--brand-surface)",
            border: "1px solid var(--brand-border)",
            fontSize: 12,
            color: "var(--text-secondary)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span>
              <strong style={{ color: "var(--text-primary)" }}>Active Scope:</strong>{" "}
              {selectedProjectId ? "Single Project" : `${totalProjects} Projects`}
            </span>
            <span>•</span>
            <span>
              <strong style={{ color: "var(--text-primary)" }}>Total Executions:</strong>{" "}
              {totalTestRuns} Runs ({totalTestCases.toLocaleString()} Tests)
            </span>
            <span>•</span>
            <span>
              <strong style={{ color: "var(--text-primary)" }}>Timeframe:</strong>{" "}
              {customRange ? `${startDate || "Start"} to ${endDate || "Today"}` : `Last ${selectedDays} Days`}
            </span>
          </div>
          {overview.usage.last_activity && (
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              Latest test execution: {new Date(overview.usage.last_activity).toLocaleString()}
            </span>
          )}
        </div>
      )}

      {/* ── Summary KPI Cards ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        {/* Projects */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Total Projects
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--accent-cyan)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {totalProjects}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Configured endpoints
          </div>
        </div>

        {/* Test Runs */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Test Runs
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--brand-primary)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {totalTestRuns}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Automated test suites
          </div>
        </div>

        {/* Test Cases */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Test Cases
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--text-primary)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {totalTestCases.toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            Total assertions evaluated
          </div>
        </div>

        {/* Pass Rate */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Overall Pass Rate
          </div>
          <div
            style={{
              fontSize: 26,
              fontWeight: 800,
              color: passPercentage >= 80 ? "var(--success)" : passPercentage >= 50 ? "var(--warning)" : "var(--danger)",
              marginTop: 6,
              fontFamily: "var(--mono)",
            }}
          >
            {passPercentage}%
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            ✓ {totalPassed} Pass / ✗ {totalFailed} Fail
          </div>
        </div>

        {/* Bugs / Failures */}
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Defect Reports
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: "var(--danger)", marginTop: 6, fontFamily: "var(--mono)" }}>
            {totalBugs}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            {openBugs} Active open defects
          </div>
        </div>
      </div>

      {/* ── Main Charts Grid ── */}
      <div className="grid-analytics-2col">
        {/* Chart 1: Test Trends Line Chart */}
        <div className="card" style={{ padding: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <div>
              <span className="card-title" style={{ fontSize: 14, fontWeight: 700 }}>
                Daily Test Execution Volume & Reliability
              </span>
              <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
                Continuous timeline of automated test runs across the active period
              </p>
            </div>
            <div style={{ display: "flex", gap: 14, fontSize: 11 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 5, color: "var(--text-secondary)" }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: "var(--brand-primary)" }} />
                Total Tests
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 5, color: "var(--text-secondary)" }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: "var(--success)" }} />
                Passed
              </span>
            </div>
          </div>

          {loading ? (
            <div style={{ height: 190, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
              Loading trend telemetry...
            </div>
          ) : trendSvg && trendSvg.points.length > 0 ? (
            <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
              <svg
                viewBox={`0 0 ${trendSvg.width} ${trendSvg.height}`}
                style={{ width: "100%", height: 190, display: "block" }}
              >
                <defs>
                  <linearGradient id="trendAreaGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--brand-primary)" stopOpacity="0.25" />
                    <stop offset="100%" stopColor="var(--brand-primary)" stopOpacity="0.0" />
                  </linearGradient>
                </defs>

                {/* Grid horizontal lines */}
                {[0, 0.25, 0.5, 0.75, 1].map((frac, idx) => {
                  const y = trendSvg.padding.top + trendSvg.chartH * (1 - frac);
                  const val = Math.round(trendSvg.maxTests * frac);
                  return (
                    <g key={idx}>
                      <line
                        x1={trendSvg.padding.left}
                        y1={y}
                        x2={trendSvg.width - trendSvg.padding.right}
                        y2={y}
                        stroke="var(--border-subtle)"
                        strokeDasharray="3 3"
                      />
                      <text
                        x={trendSvg.padding.left - 6}
                        y={y + 3}
                        fontSize="9.5"
                        fill="var(--text-muted)"
                        textAnchor="end"
                        fontFamily="var(--mono)"
                      >
                        {val}
                      </text>
                    </g>
                  );
                })}

                {/* Shaded Area */}
                {trendSvg.areaPath && (
                  <path d={trendSvg.areaPath} fill="url(#trendAreaGradient)" />
                )}

                {/* Total Line */}
                <path
                  d={trendSvg.linePath}
                  fill="none"
                  stroke="var(--brand-primary)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />

                {/* Passed Line */}
                <path
                  d={trendSvg.passedLinePath}
                  fill="none"
                  stroke="var(--success)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray="4 2"
                />

                {/* Interactive Points */}
                {trendSvg.points.map((p, idx) => (
                  <g key={idx}>
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r={hoveredTrend?.date === p.item.date ? 5 : 3.5}
                      fill="var(--bg-surface)"
                      stroke="var(--brand-primary)"
                      strokeWidth="2"
                      style={{ cursor: "pointer", transition: "all 0.2s" }}
                      onMouseEnter={() => setHoveredTrend(p.item)}
                      onMouseLeave={() => setHoveredTrend(null)}
                    />
                    {/* Date labels on bottom */}
                    {(trendSvg.points.length <= 14 || idx % Math.ceil(trendSvg.points.length / 10) === 0) && (
                      <text
                        x={p.x}
                        y={trendSvg.height - 8}
                        fontSize="9"
                        fill="var(--text-muted)"
                        textAnchor="middle"
                        fontFamily="var(--mono)"
                      >
                        {p.item.date.slice(5)}
                      </text>
                    )}
                  </g>
                ))}
              </svg>

              {/* Hover tooltip */}
              {hoveredTrend && (
                <div
                  style={{
                    position: "absolute",
                    top: 10,
                    right: 20,
                    padding: "6px 12px",
                    borderRadius: "var(--r-xs)",
                    background: "var(--bg-subtle)",
                    border: "1px solid var(--border-default)",
                    fontSize: 11,
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    pointerEvents: "none",
                    boxShadow: "var(--shadow-sm)",
                  }}
                >
                  <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{hoveredTrend.date}</span>
                  <span>Total: <strong>{hoveredTrend.total_tests}</strong></span>
                  <span style={{ color: "var(--success)" }}>Passed: {hoveredTrend.passed_tests}</span>
                  <span style={{ color: "var(--danger)" }}>Failed: {hoveredTrend.failed_tests}</span>
                  <span style={{ color: "var(--accent-cyan)", fontWeight: 700 }}>{hoveredTrend.pass_percentage}%</span>
                </div>
              )}
            </div>
          ) : (
            <div style={{ height: 190, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
              No test activity recorded in this timeframe.
            </div>
          )}
        </div>

        {/* Chart 2: Pass/Fail Donut Gauge */}
        <div className="card" style={{ padding: 22, display: "flex", flexDirection: "column" }}>
          <span className="card-title" style={{ fontSize: 14, fontWeight: 700, marginBottom: 2 }}>
            Pass / Fail Ratio
          </span>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "0 0 16px" }}>
            Aggregate test execution verification health
          </p>

          {donutSvg ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1 }}>
              <div style={{ position: "relative", width: donutSvg.size, height: donutSvg.size }}>
                <svg width={donutSvg.size} height={donutSvg.size} style={{ transform: "rotate(-90deg)" }}>
                  {/* Track circle */}
                  <circle
                    cx={donutSvg.center}
                    cy={donutSvg.center}
                    r={donutSvg.radius}
                    fill="transparent"
                    stroke="var(--bg-subtle)"
                    strokeWidth={donutSvg.strokeWidth}
                  />
                  {/* Passed segment */}
                  {totalPassed > 0 && (
                    <circle
                      cx={donutSvg.center}
                      cy={donutSvg.center}
                      r={donutSvg.radius}
                      fill="transparent"
                      stroke="var(--success)"
                      strokeWidth={donutSvg.strokeWidth}
                      strokeDasharray={`${donutSvg.passDash} ${donutSvg.circumference}`}
                      strokeDashoffset={donutSvg.passOffset}
                      strokeLinecap="round"
                    />
                  )}
                  {/* Failed segment */}
                  {totalFailed > 0 && (
                    <circle
                      cx={donutSvg.center}
                      cy={donutSvg.center}
                      r={donutSvg.radius}
                      fill="transparent"
                      stroke="var(--danger)"
                      strokeWidth={donutSvg.strokeWidth}
                      strokeDasharray={`${donutSvg.failDash} ${donutSvg.circumference}`}
                      strokeDashoffset={donutSvg.failOffset}
                      strokeLinecap="round"
                    />
                  )}
                </svg>

                {/* Center Percentage Display */}
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <span style={{ fontSize: 24, fontWeight: 800, color: "var(--text-primary)", fontFamily: "var(--mono)" }}>
                    {passPercentage}%
                  </span>
                  <span style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>
                    Pass Rate
                  </span>
                </div>
              </div>

              {/* Legend & Numbers */}
              <div style={{ display: "flex", gap: 16, marginTop: 18, width: "100%", justifyContent: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--success)" }} />
                  <span style={{ color: "var(--text-secondary)" }}>Passed:</span>
                  <strong style={{ color: "var(--success)", fontFamily: "var(--mono)" }}>{totalPassed}</strong>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--danger)" }} />
                  <span style={{ color: "var(--text-secondary)" }}>Failed:</span>
                  <strong style={{ color: "var(--danger)", fontFamily: "var(--mono)" }}>{totalFailed}</strong>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
              No test assertions executed yet.
            </div>
          )}
        </div>
      </div>

      {/* ── Secondary Charts: Project Performance & Bug Breakdown ── */}
      <div className="grid-analytics-sub">
        {/* Project Performance Comparison */}
        <div className="card" style={{ padding: 22 }}>
          <span className="card-title" style={{ fontSize: 14, fontWeight: 700 }}>
            Project Performance Benchmark
          </span>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 16px" }}>
            Comparative pass rate and execution volume per registered project
          </p>

          {projectPerformance.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {projectPerformance.map((p) => (
                <div key={p.project_id} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12.5 }}>
                    <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{p.project_name}</span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--text-secondary)" }}>
                      <strong style={{ color: p.pass_percentage >= 80 ? "var(--success)" : "var(--danger)" }}>
                        {p.pass_percentage}%
                      </strong>{" "}
                      ({p.passed_tests}/{p.total_tests} tests in {p.total_runs} runs)
                    </span>
                  </div>
                  {/* Progress Bar */}
                  <div
                    style={{
                      height: 7,
                      width: "100%",
                      borderRadius: 4,
                      background: "var(--bg-subtle)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        width: `${p.pass_percentage}%`,
                        borderRadius: 4,
                        background: p.pass_percentage >= 80 ? "var(--success)" : p.pass_percentage >= 50 ? "var(--warning)" : "var(--danger)",
                        transition: "width 0.4s ease",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
              No project statistics available. Run tests across projects to populate benchmarks.
            </div>
          )}
        </div>

        {/* Bug Severity Distribution */}
        <div className="card" style={{ padding: 22 }}>
          <span className="card-title" style={{ fontSize: 14, fontWeight: 700 }}>
            Bug Severity Breakdown
          </span>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 16px" }}>
            AI-classified defect severity distribution
          </p>

          {bugSummary?.by_severity ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                { label: "Critical", count: bugSummary.by_severity.critical || 0, color: "var(--danger)" },
                { label: "High", count: bugSummary.by_severity.high || 0, color: "var(--warning)" },
                { label: "Medium", count: bugSummary.by_severity.medium || 0, color: "var(--brand-primary)" },
                { label: "Low", count: bugSummary.by_severity.low || 0, color: "var(--success)" },
              ].map((sev) => {
                const total = totalBugs || 1;
                const pct = totalBugs > 0 ? Math.round((sev.count / total) * 100) : 0;
                return (
                  <div key={sev.label} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12 }}>
                      <span style={{ fontWeight: 600, color: sev.color }}>{sev.label}</span>
                      <span style={{ fontFamily: "var(--mono)", color: "var(--text-secondary)" }}>
                        <strong>{sev.count}</strong> ({pct}%)
                      </span>
                    </div>
                    <div style={{ height: 6, width: "100%", borderRadius: 3, background: "var(--bg-subtle)", overflow: "hidden" }}>
                      <div
                        style={{
                          height: "100%",
                          width: `${pct}%`,
                          borderRadius: 3,
                          background: sev.color,
                          transition: "width 0.4s ease",
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
              No bug reports filed.
            </div>
          )}
        </div>
      </div>

      {/* ── Recent Activity Table ── */}
      <div className="card" style={{ padding: 22 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <span className="card-title" style={{ fontSize: 14, fontWeight: 700 }}>
              Recent Test Suite Executions
            </span>
            <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
              Granular per-run verification log with direct navigation to inspection reports
            </p>
          </div>
          <span style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--mono)" }}>
            Total: {recentActivity.total} runs
          </span>
        </div>

        {recentActivity.items && recentActivity.items.length > 0 ? (
          <>
            <div className="history-table" style={{ overflowX: "auto" }}>
              <div
                className="history-th-row"
                style={{
                  gridTemplateColumns: "70px 1.5fr 110px 110px 80px 100px",
                  borderBottom: "1px solid var(--border-default)",
                }}
              >
                <span>Run ID</span>
                <span>Project Name</span>
                <span>Created At</span>
                <span>Test Count</span>
                <span>Status</span>
                <span style={{ textAlign: "right" }}>Action</span>
              </div>

              {recentActivity.items.map((run) => (
                <div
                  key={run.run_id}
                  className="history-td-row"
                  style={{
                    gridTemplateColumns: "70px 1.5fr 110px 110px 80px 100px",
                    cursor: "pointer",
                  }}
                  onClick={() => onViewRun && onViewRun(run.run_id)}
                >
                  <span className="history-run-id">#{run.run_id}</span>
                  <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{run.project_name}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {run.created_at ? new Date(run.created_at).toLocaleDateString() : "—"}
                  </span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--text-secondary)" }}>
                    {run.total_tests} ({run.passed_tests}✓ / {run.failed_tests}✗)
                  </span>
                  <span>
                    <span
                      style={{
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 10.5,
                        fontWeight: 700,
                        background: run.status === "PASS" ? "var(--success-surface)" : "var(--danger-surface)",
                        color: run.status === "PASS" ? "var(--success)" : "var(--danger)",
                        border: `1px solid ${run.status === "PASS" ? "var(--success-border)" : "var(--danger-border)"}`,
                      }}
                    >
                      {run.status}
                    </span>
                  </span>
                  <span style={{ textAlign: "right" }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ fontSize: 11, padding: "2px 8px" }}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (onViewRun) onViewRun(run.run_id);
                      }}
                    >
                      Inspect →
                    </button>
                  </span>
                </div>
              ))}
            </div>

            {/* Pagination Controls */}
            {recentActivity.total > activityLimit && (
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
                  disabled={activityPage === 0}
                  onClick={() => setActivityPage((p) => Math.max(0, p - 1))}
                  style={{ fontSize: 12 }}
                >
                  ← Previous
                </button>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Page {activityPage + 1} of {Math.ceil(recentActivity.total / activityLimit)}
                </span>
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={(activityPage + 1) * activityLimit >= recentActivity.total}
                  onClick={() => setActivityPage((p) => p + 1)}
                  style={{ fontSize: 12 }}
                >
                  Next →
                </button>
              </div>
            )}
          </>
        ) : (
          <div style={{ padding: "40px 20px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            No recent activity recorded for this selection.
          </div>
        )}
      </div>
    </div>
  );
}
