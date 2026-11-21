import { useState, useEffect, useRef, useCallback } from "react";
import "./App.css";
import { AuthPage } from "./components/Auth.jsx";
import { ProjectsPage } from "./components/Projects.jsx";
import { AnalyticsPage } from "./components/Analytics.jsx";
import { AdminDashboard } from "./components/AdminDashboard.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { Topbar } from "./components/Topbar.jsx";
import { ThemeToggle } from "./components/ThemeToggle.jsx";
import { ResultsView } from "./components/ResultsView.jsx";
import { BugsView } from "./components/BugsView.jsx";
import { UsageView } from "./components/UsageView.jsx";
import { SettingsView } from "./components/SettingsView.jsx";
import { RunProgress } from "./components/RunProgress.jsx";
import { RunHistory } from "./components/RunHistory.jsx";


/* ══════════════════════════════════════════════════════
   UTILITIES
══════════════════════════════════════════════════════ */
const methodColor = { GET: "#10b981", POST: "#3b82f6", PUT: "#f59e0b", DELETE: "#f43f5e", PATCH: "#8b5cf6" };
const getMethodColor = (m = "") => methodColor[m.toUpperCase()] || "#8892a4";

/* ══════════════════════════════════════════════════════
   ANIMATED NUMBER
══════════════════════════════════════════════════════ */
function AnimatedNumber({ value, suffix = "" }) {
  const [display, setDisplay] = useState(0);
  const raf = useRef(null);
  useEffect(() => {
    const target = parseFloat(value) || 0;
    const start = performance.now();
    const dur = 900;
    const tick = (now) => {
      const p = Math.min((now - start) / dur, 1);
      const e = 1 - Math.pow(1 - p, 3);
      setDisplay(Math.round(target * e));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [value]);
  return <>{display}{suffix}</>;
}

/* ══════════════════════════════════════════════════════
   DONUT CHART
══════════════════════════════════════════════════════ */
function DonutChart({ passed, failed, total }) {
  const r = 54, size = 140, circ = 2 * Math.PI * r;
  const pct = total > 0 ? passed / total : 0;
  const fPct = total > 0 ? failed / total : 0;
  const passArc = circ * pct;
  const failArc = circ * fPct;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)", flexShrink: 0 }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="16"/>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#10b981" strokeWidth="16"
          strokeDasharray={`${passArc} ${circ}`} strokeDashoffset="0" strokeLinecap="round"
          style={{ transition: "stroke-dasharray 1.2s cubic-bezier(0.4,0,0.2,1)" }}/>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#f43f5e" strokeWidth="16"
          strokeDasharray={`${failArc} ${circ}`} strokeDashoffset={`-${passArc}`} strokeLinecap="round"
          style={{ transition: "all 1.2s cubic-bezier(0.4,0,0.2,1) 0.15s" }}/>
        <g transform={`rotate(90 ${size/2} ${size/2})`}>
          <text x={size/2} y={size/2 - 7} textAnchor="middle" fill="#f0f4ff" fontSize="22" fontWeight="800" fontFamily="Inter,sans-serif">
            {total > 0 ? `${((passed/total)*100).toFixed(0)}%` : "—"}
          </text>
          <text x={size/2} y={size/2 + 14} textAnchor="middle" fill="#4a5568" fontSize="9.5" fontFamily="Inter,sans-serif" fontWeight="600" letterSpacing="0.8">PASS RATE</text>
        </g>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {[["#10b981","Passed", passed],["#f43f5e","Failed", failed],["#3b82f6","Total", total]].map(([color,label,val])=>(
          <div key={label} style={{ display:"flex", alignItems:"center", gap:10, fontSize:13 }}>
            <div style={{ width:10, height:10, borderRadius:"50%", background:color, flexShrink:0 }}/>
            <span style={{ color:"var(--text-secondary)" }}>{label}</span>
            <span style={{ fontWeight:700, color:"var(--text-primary)", marginLeft:"auto", minWidth:28, textAlign:"right" }}>{val}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   PAGE: DASHBOARD (Overview & Testing Command Center)
══════════════════════════════════════════════════════ */
function DashboardPage({
  testData,
  onRunTests,
  loading,
  onNavigate,
  baseUrl,
  setBaseUrl,
  openapiUrl,
  setOpenapiUrl,
  selectedProject,
  activeRun,
  onCancelRun,
  onCompleteRun,
  apiBaseUrl,
  token,
  runNotice,
  onDismissNotice,
}) {
  const total    = testData?.total    ?? 0;
  const passed   = testData?.passed   ?? 0;
  const failed   = testData?.failed   ?? 0;
  const passRate = testData ? parseFloat(testData.pass_rate) : 0;
  const aiCount  = testData ? testData.results.filter(t => t.test_id?.startsWith("AI-")).length : 0;
  const ruleCount= testData ? testData.results.filter(t => !t.test_id?.startsWith("AI-")).length : 0;
  const bugsFound= testData ? testData.results.filter(t => t.bug_report).length : 0;

  const statCards = [
    { label: "Total Tests",    value: total,    icon: "📊", color: "blue",   suffix: "" },
    { label: "Passed Tests",   value: passed,   icon: "✓",  color: "green",  suffix: "" },
    { label: "Failed Tests",   value: failed,   icon: "✗",  color: "rose",   suffix: "" },
    { label: "Pass Rate",      value: passRate, icon: "🎯", color: "violet", suffix: "%" },
  ];

  return (
    <div className="page fade-in" style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* ── Command Center Header ── */}
      <div className="welcome-banner" style={{ marginBottom: 20 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
              Testing Command Center
            </h1>
            {selectedProject ? (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "3px 10px",
                  borderRadius: "var(--r-full)",
                  background: "var(--brand-surface)",
                  color: "var(--brand-primary)",
                  border: "1px solid var(--brand-border)",
                }}
              >
                📁 {selectedProject.project_name}
              </span>
            ) : (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "3px 10px",
                  borderRadius: "var(--r-full)",
                  background: "var(--bg-subtle)",
                  color: "var(--text-muted)",
                  border: "1px solid var(--border-default)",
                }}
              >
                🌐 Default Target API
              </span>
            )}
          </div>
          <p className="page-sub">
            {testData
              ? `Last suite execution: ${total} tests executed (${passed} passed, ${failed} failed) · Overall pass rate: ${passRate}%`
              : "Ready to execute automated rule-based assertions and AI fuzz testing."}
          </p>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => onNavigate("projects")}
            style={{ fontSize: 12.5 }}
          >
            📁 Workspaces
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onRunTests}
            disabled={loading}
            style={{ fontSize: 13 }}
          >
            {loading ? (
              <>
                <div className="spinner" style={{ width: 14, height: 14 }} />
                Executing Suite…
              </>
            ) : (
              <>▶ Run Test Suite</>
            )}
          </button>
        </div>
      </div>

      {/* ── Queued / Progress Status Banner ── */}
      {runNotice && (
        <div
          className="card fade-in"
          style={{
            marginBottom: 16,
            padding: "12px 18px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background:
              runNotice.type === "success"
                ? "rgba(16, 185, 129, 0.12)"
                : runNotice.type === "error"
                ? "rgba(244, 63, 94, 0.12)"
                : "rgba(59, 130, 246, 0.12)",
            border: `1px solid ${
              runNotice.type === "success"
                ? "var(--success)"
                : runNotice.type === "error"
                ? "var(--danger)"
                : "var(--brand-primary)"
            }`,
            borderRadius: "var(--r-md)",
            color: "var(--text-primary)",
            fontSize: 13,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span>{runNotice.type === "success" ? "✓" : runNotice.type === "error" ? "⚠" : "ℹ"}</span>
            <span>{runNotice.message}</span>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onDismissNotice}
            style={{ fontSize: 14 }}
            aria-label="Dismiss notification"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Active Background Execution Progress ── */}
      {activeRun && (
        <RunProgress
          runId={activeRun.id}
          activeRun={activeRun}
          projectName={selectedProject?.project_name}
          apiBaseUrl={apiBaseUrl}
          token={token}
          onComplete={onCompleteRun}
          onCancel={onCancelRun}
          onNavigate={onNavigate}
        />
      )}

      {/* ── Active Workspace Status Card ── */}
      {selectedProject && (
        <div
          className="card"
          style={{
            marginBottom: 20,
            padding: "16px 20px",
            background: "linear-gradient(135deg, var(--brand-surface) 0%, var(--bg-surface) 100%)",
            border: "1px solid var(--brand-border)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 12,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div
                className="project-card-orb"
                style={{
                  background: "var(--brand-surface)",
                  borderColor: "var(--brand-border)",
                  fontSize: 18,
                }}
              >
                ⚡
              </div>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
                    {selectedProject.project_name}
                  </h3>
                  <span
                    style={{
                      fontSize: 10.5,
                      padding: "2px 7px",
                      borderRadius: "var(--r-xs)",
                      fontWeight: 600,
                      background:
                        selectedProject.auth_type !== "none"
                          ? "var(--brand-surface)"
                          : "var(--bg-subtle)",
                      color:
                        selectedProject.auth_type !== "none"
                          ? "var(--brand-primary)"
                          : "var(--text-muted)",
                      border: `1px solid ${
                        selectedProject.auth_type !== "none"
                          ? "var(--brand-border)"
                          : "var(--border-default)"
                      }`,
                    }}
                  >
                    {selectedProject.auth_type === "bearer"
                      ? "Bearer Token"
                      : selectedProject.auth_type === "api_key"
                      ? selectedProject.auth_header_name || "API Key"
                      : "Public API"}
                  </span>
                  {selectedProject.has_credentials ? (
                    <span style={{ fontSize: 11, color: "var(--success)", fontWeight: 600 }}>
                      🔒 Encrypted
                    </span>
                  ) : selectedProject.auth_type !== "none" ? (
                    <span style={{ fontSize: 11, color: "var(--danger)", fontWeight: 600 }}>
                      ⚠ No Secret Configured
                    </span>
                  ) : null}
                </div>
                <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
                  Target Endpoint:{" "}
                  <code style={{ fontFamily: "var(--mono)", color: "var(--brand-primary)" }}>
                    {selectedProject.base_url}
                  </code>{" "}
                  &bull; OpenAPI:{" "}
                  <code style={{ fontFamily: "var(--mono)", color: "var(--text-muted)" }}>
                    {selectedProject.openapi_url || "Auto-detected"}
                  </code>
                </p>
              </div>
            </div>

            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => onNavigate("projects")}
              >
                Switch Workspace
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Quick Developer Actions Bar ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 12,
          marginBottom: 20,
        }}
      >
        <button
          type="button"
          className="card"
          onClick={onRunTests}
          disabled={loading}
          style={{
            padding: "14px 16px",
            display: "flex",
            alignItems: "center",
            gap: 12,
            cursor: loading ? "not-allowed" : "pointer",
            textAlign: "left",
            border: "1px solid var(--border-default)",
            transition: "var(--t)",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: "var(--r-sm)",
              background: "var(--brand-surface)",
              color: "var(--brand-primary)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 14,
              flexShrink: 0,
            }}
          >
            ▶
          </div>
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)" }}>
              Run Test Suite
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Rule-based & AI fuzzing
            </div>
          </div>
        </button>

        <button
          type="button"
          className="card"
          onClick={() => onNavigate("projects")}
          style={{
            padding: "14px 16px",
            display: "flex",
            alignItems: "center",
            gap: 12,
            cursor: "pointer",
            textAlign: "left",
            border: "1px solid var(--border-default)",
            transition: "var(--t)",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: "var(--r-sm)",
              background: "var(--info-surface)",
              color: "var(--info)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 14,
              flexShrink: 0,
            }}
          >
            📁
          </div>
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)" }}>
              Workspaces & Auth
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Configure targets & keys
            </div>
          </div>
        </button>

        <button
          type="button"
          className="card"
          onClick={() => onNavigate("history")}
          style={{
            padding: "14px 16px",
            display: "flex",
            alignItems: "center",
            gap: 12,
            cursor: "pointer",
            textAlign: "left",
            border: "1px solid var(--border-default)",
            transition: "var(--t)",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: "var(--r-sm)",
              background: "rgba(139, 92, 246, 0.12)",
              color: "#8b5cf6",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 14,
              flexShrink: 0,
            }}
          >
            🕒
          </div>
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)" }}>
              Run History
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Execution pass/fail logs
            </div>
          </div>
        </button>

        <button
          type="button"
          className="card"
          onClick={() => onNavigate("analytics")}
          style={{
            padding: "14px 16px",
            display: "flex",
            alignItems: "center",
            gap: 12,
            cursor: "pointer",
            textAlign: "left",
            border: "1px solid var(--border-default)",
            transition: "var(--t)",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: "var(--r-sm)",
              background: "var(--success-surface)",
              color: "var(--success)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 14,
              flexShrink: 0,
            }}
          >
            📊
          </div>
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)" }}>
              Defect Telemetry
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Quality trends & health
            </div>
          </div>
        </button>
      </div>

      {/* ── KPI Metric Cards ── */}
      <div className="stats-grid">
        {statCards.map((c, i) => (
          <div key={c.label} className={`stat-card ${c.color}`} style={{ animationDelay: `${i * 0.07}s` }}>
            <div className={`stat-icon ${c.color}`}>{c.icon}</div>
            <div className="stat-label">{c.label}</div>
            <div className="stat-value">
              {testData ? (
                <AnimatedNumber value={c.value} suffix={c.suffix} />
              ) : (
                <span style={{ color: "var(--text-muted)" }}>—</span>
              )}
            </div>
            {c.label === "Pass Rate" && (
              <div className="progress-bar-wrap">
                <div
                  className="progress-bar-fill"
                  style={{
                    width: testData ? `${passRate}%` : "0%",
                    background:
                      passRate >= 80
                        ? "var(--success)"
                        : passRate >= 50
                        ? "var(--warning)"
                        : "var(--danger)",
                  }}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ── Target API Parameter Configuration ── */}
      <div className="card" style={{ marginBottom: 20, padding: "18px 22px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
              Active Target Specification
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
              {selectedProject
                ? `Bound to workspace "${selectedProject.project_name}". Adjustments here apply to the next test execution.`
                : "Configure endpoints for on-the-fly execution or save them inside an API Project workspace."}
            </p>
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gap: 16,
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            marginTop: 10,
          }}
        >
          <div className="auth-field">
            <label style={{ fontSize: 11.5, fontWeight: 700, color: "var(--text-secondary)" }}>
              TARGET BASE URL
            </label>
            <input
              type="url"
              className="auth-input"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000"
              style={{ fontSize: 12.5 }}
            />
          </div>

          <div className="auth-field">
            <label style={{ fontSize: 11.5, fontWeight: 700, color: "var(--text-secondary)" }}>
              OPENAPI SPECIFICATION URL
            </label>
            <input
              type="url"
              className="auth-input"
              value={openapiUrl}
              onChange={(e) => setOpenapiUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000/openapi.json"
              style={{ fontSize: 12.5 }}
            />
          </div>
        </div>
      </div>

      {/* ── Analytics Visualizations ── */}
      <div className="grid-2col" style={{ marginBottom: 20 }}>
        {/* Pass / Fail Donut */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Verdict Distribution</span>
            <span className="card-badge blue">{testData ? "Execution Complete" : "Standby"}</span>
          </div>
          <div style={{ marginTop: 12 }}>
            <DonutChart passed={passed} failed={failed} total={total} />
          </div>
        </div>

        {/* Test Generation Mix */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Test Generation Telemetry</span>
          </div>
          <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 14 }}>
            <div className="gen-bar-row">
              <span className="gen-bar-label">⚙️ Rule-Based Tests</span>
              <div className="gen-bar-track">
                <div
                  className="gen-bar-fill blue"
                  style={{ width: total > 0 ? `${(ruleCount / total) * 100}%` : "0%" }}
                />
              </div>
              <span className="gen-bar-num">{ruleCount}</span>
            </div>

            <div className="gen-bar-row">
              <span className="gen-bar-label">🤖 AI-Generated Tests</span>
              <div className="gen-bar-track">
                <div
                  className="gen-bar-fill violet"
                  style={{ width: total > 0 ? `${(aiCount / total) * 100}%` : "0%" }}
                />
              </div>
              <span className="gen-bar-num">{aiCount}</span>
            </div>

            <div className="gen-bar-row">
              <span className="gen-bar-label">🐛 Detected Defects</span>
              <div className="gen-bar-track">
                <div
                  className="gen-bar-fill rose"
                  style={{ width: total > 0 ? `${(bugsFound / total) * 100}%` : "0%" }}
                />
              </div>
              <span className="gen-bar-num">{bugsFound}</span>
            </div>
          </div>

          {/* Quick Result Shortcuts */}
          <div style={{ marginTop: 24, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button
              type="button"
              className="shortcut-btn"
              onClick={() => onNavigate("results")}
            >
              Inspect Test Results →
            </button>
            <button
              type="button"
              className="shortcut-btn rose"
              onClick={() => onNavigate("bugs")}
            >
              Inspect Defect Reports ({bugsFound}) →
            </button>
          </div>
        </div>
      </div>

      {/* ── Recent Failures Section ── */}
      {testData && failed > 0 && (
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header" style={{ marginBottom: 12 }}>
            <span className="card-title" style={{ color: "var(--danger)" }}>
              ⚠ Recent Failures Requiring Attention
            </span>
            <button
              type="button"
              className="shortcut-btn rose"
              onClick={() => onNavigate("bugs")}
              style={{ fontSize: 11 }}
            >
              See all {failed} failure reports →
            </button>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {testData.results
              .filter((t) => t.status === "FAIL")
              .slice(0, 4)
              .map((t) => (
                <div key={t.test_id} className="quick-fail-row">
                  <span className="qf-id">{t.test_id}</span>
                  <span
                    className="qf-method"
                    style={{
                      color: getMethodColor(t.method),
                      fontFamily: "var(--mono)",
                      fontWeight: 700,
                    }}
                  >
                    {t.method}
                  </span>
                  <span className="qf-ep" title={t.endpoint}>
                    {t.endpoint}
                  </span>
                  <span className="qf-reason" title={t.failure_reason}>
                    {t.failure_reason?.slice(0, 70) || "Assertion failed."}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* ── Clean Empty State when No Tests Have Executed ── */}
      {!testData && (
        <div className="empty-cta" style={{ marginTop: 10 }}>
          <div className="empty-cta-icon">🚀</div>
          <h3 style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>
            Automated API Testing Command Center
          </h3>
          <p
            style={{
              color: "var(--text-secondary)",
              fontSize: 13.5,
              maxWidth: 480,
              margin: "0 auto 20px",
              lineHeight: 1.55,
            }}
          >
            Execute comprehensive schema conformance tests, status code checks, payload validation, and Gemini AI failure analysis against your OpenAPI specifications.
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={onRunTests}
              disabled={loading}
            >
              {loading ? (
                <>
                  <div className="spinner" style={{ width: 14, height: 14 }} />
                  Running Suite…
                </>
              ) : (
                <>▶ Execute First Test Run</>
              )}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onNavigate("projects")}
            >
              📁 Manage API Workspaces
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   PAGES: TEST RESULTS & BUG REPORTS (modularized in ./components/ResultsView.jsx & ./components/BugsView.jsx)
══════════════════════════════════════════════════════ */

/* ══════════════════════════════════════════════════════
   PAGE: HISTORY (modularized in ./components/RunHistory.jsx)
══════════════════════════════════════════════════════ */

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || "http://127.0.0.1:5000"
).replace(/\/+$/, "");

/* ══════════════════════════════════════════════════════
   ROOT APP
══════════════════════════════════════════════════════ */
export default function App() {
  const [token, setToken]                 = useState(() => localStorage.getItem("auth_token"));
  const [currentUser, setCurrentUser]     = useState(null);
  const [authLoading, setAuthLoading]     = useState(true);

  const [page, setPage]                   = useState("dashboard");
  const [testData, setTestData]           = useState(null);
  const [loading, setLoading]             = useState(false);
  const [isSubmitting, setIsSubmitting]   = useState(false);
  const [activeRunId, setActiveRunId]     = useState(null);
  const [activeRun, setActiveRun]         = useState(null);
  const [runNotice, setRunNotice]         = useState(null);
  const isPollingBusyRef                  = useRef(false);
  const [error, setError]                 = useState("");
  const [testRuns, setTestRuns]           = useState([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [baseUrl, setBaseUrl]             = useState("http://127.0.0.1:8000");
  const [openapiUrl, setOpenapiUrl]       = useState(
    "http://127.0.0.1:8000/openapi.json"
  );
  const [selectedProject, setSelectedProject] = useState(null);

  // Theme Management (Dark / Light with localStorage persistence)
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem("app_theme");
    if (saved === "light" || saved === "dark") return saved;
    return "dark";
  });

  // Responsive Drawer state
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("app_theme", theme);
  }, [theme]);

  const handleToggleTheme = useCallback(() => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  const handleSelectProject = useCallback((proj) => {
    setSelectedProject(proj);
    if (proj) {
      setBaseUrl(proj.base_url);
      if (proj.openapi_url) {
        setOpenapiUrl(proj.openapi_url);
      } else {
        setOpenapiUrl(`${proj.base_url.replace(/\/+$/, "")}/openapi.json`);
      }
    }
  }, []);


  // Authenticate / Restore session on load
  useEffect(() => {
    let isMounted = true;
    const verifySession = async () => {
      const savedToken = localStorage.getItem("auth_token");
      if (!savedToken) {
        if (isMounted) setAuthLoading(false);
        return;
      }

      try {
        const res = await fetch(`${API_BASE_URL}/auth/me`, {
          headers: {
            Authorization: `Bearer ${savedToken}`,
          },
        });

        if (res.ok) {
          const json = await res.json();
          if (isMounted) {
            setCurrentUser(json.data);
            setToken(savedToken);

            // Restore active background job if in-flight across page refresh
            const savedActiveRunId = localStorage.getItem("active_run_id");
            if (savedActiveRunId) {
              fetch(`${API_BASE_URL}/test-runs/${savedActiveRunId}`, {
                headers: { Authorization: `Bearer ${savedToken}` },
              })
                .then((r) => (r.ok ? r.json() : null))
                .then((runJson) => {
                  if (runJson && isMounted) {
                    const rData = runJson.data;
                    if (rData && (rData.status === "queued" || rData.status === "running")) {
                      setActiveRunId(Number(savedActiveRunId));
                      setActiveRun(rData);
                    } else {
                      localStorage.removeItem("active_run_id");
                    }
                  }
                })
                .catch(() => {});
            }
          }
        } else {
          // Token expired or invalid
          localStorage.removeItem("auth_token");
          if (isMounted) {
            setToken(null);
            setCurrentUser(null);
          }
        }
      } catch {
        // Network error - retain saved token in case of brief server restart
      } finally {
        if (isMounted) setAuthLoading(false);
      }
    };

    verifySession();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleLoginSuccess = (newToken, user) => {
    localStorage.setItem("auth_token", newToken);
    setToken(newToken);
    setCurrentUser(user);
    setError("");
    setPage("dashboard");
  };

  const handleLogout = useCallback(async () => {
    const savedToken = localStorage.getItem("auth_token") || token;
    if (savedToken) {
      try {
        await fetch(`${API_BASE_URL}/auth/logout`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${savedToken}`,
          },
        });
      } catch {
        // Stateless JWT logout - ignore failure
      }
    }

    localStorage.removeItem("auth_token");
    localStorage.removeItem("active_run_id");
    setToken(null);
    setCurrentUser(null);
    setTestData(null);
    setTestRuns([]);
    setActiveRunId(null);
    setActiveRun(null);
    setRunNotice(null);
    setPage("dashboard");
  }, [token]);

  const loadHistory = useCallback(async () => {
    try {
      const headers = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const res = await fetch(`${API_BASE_URL}/test-runs`, { headers });
      if (res.status === 401) {
        handleLogout();
        return;
      }
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTestRuns(data.data || []);
      setHistoryLoaded(true);
    } catch {
      setError("Cannot load history.");
    }
  }, [token, handleLogout]);

  const loadRunResults = useCallback(async (runId) => {
    try {
      const headers = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const [resR, resB] = await Promise.all([
        fetch(`${API_BASE_URL}/test-runs/${runId}/results`, { headers }),
        fetch(`${API_BASE_URL}/test-runs/${runId}/bugs`, { headers }),
      ]);

      if (resR.status === 401 || resB.status === 401) {
        handleLogout();
        return;
      }

      // 409 Conflict: run is still queued or running
      if (resR.status === 409 || resB.status === 409) {
        setActiveRunId(runId);
        setPage("dashboard");
        return;
      }

      if (!resR.ok || !resB.ok) {
        throw new Error("Failed to load run results.");
      }

      const [rData, bData] = await Promise.all([resR.json(), resB.json()]);
      const merged = (rData.data || []).map(test => {
        const norm = {
          ...test,
          expected_status: test.expected_status ?? test.expected?.status_code ?? null,
          actual_status:   test.actual_status   ?? test.actual?.status_code   ?? null,
          expected_body:   test.expected_body   ?? test.expected_schema       ?? test.expected?.response_schema ?? test.expected?.body ?? null,
          actual_body:     test.actual_body     ?? test.actual?.body           ?? null,
        };
        const bug = (bData.data || []).find(b => b.test_id === test.test_id);
        if (!bug) return norm;
        return { ...norm, ai_analysis:{ summary:bug.summary, possible_cause:bug.possible_cause, severity:bug.severity, recommendation:bug.recommendation }, bug_report:bug };
      });
      const total = merged.length;
      const passed = merged.filter(t => t.status==="PASS").length;
      const failed = merged.filter(t => t.status==="FAIL").length;
      setTestData({ results:merged, total, passed, failed, pass_rate: total>0?((passed/total)*100).toFixed(2):0 });
      setPage("results");
    } catch (err) {
      setError(err.message || "Failed to load run results.");
    }
  }, [token, handleLogout]);

  // Polling effect for active background job
  useEffect(() => {
    if (!activeRunId) return;

    let isMounted = true;
    let consecutiveFailures = 0;

    const pollJob = async () => {
      if (isPollingBusyRef.current) return;
      isPollingBusyRef.current = true;
      try {
        const headers = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE_URL}/test-runs/${activeRunId}`, { headers });
        if (!isMounted) return;

        if (res.status === 401) {
          handleLogout();
          return;
        }

        if (!res.ok) {
          consecutiveFailures += 1;
          if (consecutiveFailures >= 6) {
            setError(`Unable to poll status for run #${activeRunId}. Retrying...`);
          }
          return;
        }

        consecutiveFailures = 0;
        const json = await res.json();
        const data = json.data;
        if (!data || !isMounted) return;

        setActiveRun(data);

        if (data.status === "completed") {
          localStorage.removeItem("active_run_id");
          clearInterval(pollTimer);
          setRunNotice({
            type: "success",
            message: `Test run #${activeRunId} completed! Loading results...`,
          });
          await loadRunResults(activeRunId);
          loadHistory();
        } else if (data.status === "failed") {
          localStorage.removeItem("active_run_id");
          clearInterval(pollTimer);
          setRunNotice({
            type: "error",
            message: `Test run #${activeRunId} failed: ${data.error_message || "Execution error"}`,
          });
          loadHistory();
        } else if (data.status === "cancelled") {
          localStorage.removeItem("active_run_id");
          clearInterval(pollTimer);
          setRunNotice({
            type: "info",
            message: `Test run #${activeRunId} was cancelled.`,
          });
          loadHistory();
        }
      } catch {
        consecutiveFailures += 1;
        // Don't reset run state on network blip
      } finally {
        isPollingBusyRef.current = false;
      }
    };

    pollJob();
    const pollTimer = setInterval(pollJob, 2500);

    return () => {
      isMounted = false;
      clearInterval(pollTimer);
      isPollingBusyRef.current = false;
    };
  }, [activeRunId, token, handleLogout, loadRunResults, loadHistory]);

  const cancelActiveRun = useCallback(async (runIdToCancel) => {
    const targetId = runIdToCancel || activeRunId;
    if (!targetId) return;

    try {
      const headers = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${API_BASE_URL}/test-runs/${targetId}/cancel`, {
        method: "POST",
        headers,
      });

      if (res.status === 401) {
        handleLogout();
        return;
      }

      if (res.ok) {
        localStorage.removeItem("active_run_id");
        setActiveRun((prev) => prev ? { ...prev, status: "cancelled" } : { id: targetId, status: "cancelled" });
        setRunNotice({
          type: "info",
          message: `Test run #${targetId} cancelled successfully.`,
        });
        loadHistory();
      } else {
        const errorText = await res.text();
        setError(errorText || "Could not cancel test run.");
        // Refresh status in case it finished during race
        const statusRes = await fetch(`${API_BASE_URL}/test-runs/${targetId}`, { headers });
        if (statusRes.ok) {
          const statusJson = await statusRes.json();
          setActiveRun(statusJson.data);
          if (statusJson.data?.status === "completed") {
            localStorage.removeItem("active_run_id");
            await loadRunResults(targetId);
          }
        }
      }
    } catch {
      setError("Network error while attempting to cancel test run.");
    }
  }, [activeRunId, token, handleLogout, loadHistory, loadRunResults]);

  const runTests = useCallback(async (projectOverride = null) => {
    const proj = projectOverride || selectedProject;
    if (!proj) {
      setError("Please select an API Project Workspace before running tests.");
      setPage("projects");
      return;
    }

    if (isSubmitting || loading) return;
    setIsSubmitting(true);
    setLoading(true);
    setError("");

    try {
      const idempotencyKey = crypto.randomUUID
        ? crypto.randomUUID()
        : `run-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

      const headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const targetBaseUrl = (baseUrl || proj.base_url || "http://127.0.0.1:8000").trim();
      const targetOpenApi = (openapiUrl || proj.openapi_url || `${targetBaseUrl}/openapi.json`).trim();

      const res = await fetch(`${API_BASE_URL}/test-runs`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          project_id: proj.id,
          base_url: targetBaseUrl,
          openapi_url: targetOpenApi,
          idempotency_key: idempotencyKey,
        }),
      });

      if (res.status === 401) {
        handleLogout();
        throw new Error("Session expired. Please sign in again.");
      }

      if (!res.ok && res.status !== 202) {
        const message = await res.text();
        throw new Error(message || "Test execution request failed.");
      }

      const json = await res.json();
      const runId = json.data?.run_id;
      const runStatus = json.data?.status || "queued";

      localStorage.setItem("active_run_id", runId.toString());
      setActiveRunId(runId);
      setActiveRun({
        id: runId,
        project_id: proj.id,
        project_name: proj.project_name,
        status: runStatus,
        created_at: new Date().toISOString(),
      });
      setRunNotice({
        type: "success",
        message: `Test run #${runId} queued successfully! Background worker will execute the test suite.`,
      });

      setPage("dashboard");
    } catch (err) {
      setError(
        err.message || "Cannot reach backend. Ensure both servers are running."
      );
    } finally {
      setIsSubmitting(false);
      setLoading(false);
    }
  }, [baseUrl, openapiUrl, token, selectedProject, isSubmitting, loading, handleLogout]);

  const runTestsWithProject = useCallback((proj) => {
    handleSelectProject(proj);
    runTests(proj);
  }, [handleSelectProject, runTests]);

  // Auto-load history when switching to history tab
  useEffect(() => {
    if (page !== "history" || historyLoaded) return;
    let ignore = false;

    const fetchHistory = async () => {
      try {
        const headers = {};
        if (token) {
          headers["Authorization"] = `Bearer ${token}`;
        }

        const res = await fetch(`${API_BASE_URL}/test-runs`, { headers });
        if (res.status === 401) {
          handleLogout();
          return;
        }
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (!ignore) {
          setTestRuns(data.data);
          setHistoryLoaded(true);
        }
      } catch {
        if (!ignore) {
          setError("Cannot load history.");
        }
      }
    };

    fetchHistory();

    return () => {
      ignore = true;
    };
  }, [page, historyLoaded, token, handleLogout]);


  // 1. Loading screen while verifying token
  if (authLoading) {
    return (
      <div className="auth-loading-screen">
        <div className="logo-orb" style={{ width: 52, height: 52, fontSize: 24 }}>🤖</div>
        <div className="spinner" style={{ width: 22, height: 22 }} />
        <p className="auth-loading-text">Verifying authentication session…</p>
      </div>
    );
  }

  // 2. Unauthenticated user view
  if (!currentUser) {
    return (
      <div style={{ position: "relative", minHeight: "100vh" }}>
        <div style={{ position: "absolute", top: 16, right: 20, zIndex: 10 }}>
          <ThemeToggle theme={theme} onToggle={handleToggleTheme} />
        </div>
        <AuthPage
          apiBaseUrl={API_BASE_URL}
          onLoginSuccess={handleLoginSuccess}
        />
      </div>
    );
  }

  // 3. Authenticated dashboard view
  return (
    <div className="app">
      {/* ── Modern Responsive Sidebar ── */}
      <Sidebar
        page={page}
        onNavigate={setPage}
        currentUser={currentUser}
        onLogout={handleLogout}
        testData={testData}
        selectedProject={selectedProject}
        loading={loading || isSubmitting || activeRun?.status === "queued" || activeRun?.status === "running"}
        onRunTests={() => runTests()}
        onRefreshHistory={loadHistory}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
      />

      {/* ── Main Content Area ── */}
      <main className="main-content">
        {/* Topbar */}
        <Topbar
          page={page}
          selectedProject={selectedProject}
          onNavigate={setPage}
          currentUser={currentUser}
          theme={theme}
          onToggleTheme={handleToggleTheme}
          onLogout={handleLogout}
          onRunTests={() => runTests()}
          loading={loading || isSubmitting || activeRun?.status === "queued" || activeRun?.status === "running"}
          testData={testData}
          onOpenMobileNav={() => setMobileNavOpen(true)}
        />

        {/* Error */}
        {error && (
          <div className="error-banner">
            ⚠ {error}
            <button className="icon-btn" style={{ marginLeft: "auto" }} onClick={() => setError("")}>✕</button>
          </div>
        )}

        {/* Pages */}
        {page === "projects" && (
          <ProjectsPage
            apiBaseUrl={API_BASE_URL}
            token={token}
            selectedProject={selectedProject}
            onSelectProject={handleSelectProject}
            onRunTestsWithProject={runTestsWithProject}
          />
        )}
        {page === "analytics" && (
          <AnalyticsPage
            apiBaseUrl={API_BASE_URL}
            token={token}
            onViewRun={loadRunResults}
            onNavigate={setPage}
          />
        )}
        {page === "dashboard" && (
          <DashboardPage
            testData={testData}
            onRunTests={() => runTests()}
            loading={loading || isSubmitting || activeRun?.status === "queued" || activeRun?.status === "running"}
            onNavigate={setPage}
            baseUrl={baseUrl}
            setBaseUrl={setBaseUrl}
            openapiUrl={openapiUrl}
            setOpenapiUrl={setOpenapiUrl}
            selectedProject={selectedProject}
            currentUser={currentUser}
            activeRun={activeRun}
            onCancelRun={cancelActiveRun}
            onCompleteRun={(runData) => {
              loadRunResults(runData.id);
              loadHistory();
            }}
            apiBaseUrl={API_BASE_URL}
            token={token}
            runNotice={runNotice}
            onDismissNotice={() => setRunNotice(null)}
          />
        )}
        {page === "results" && (
          <ResultsView
            testData={testData}
            selectedProject={selectedProject}
            onNavigate={setPage}
            activeRun={activeRun}
            apiBaseUrl={API_BASE_URL}
            token={token}
            onCancelRun={cancelActiveRun}
            onCompleteRun={(runData) => {
              loadRunResults(runData.id);
              loadHistory();
            }}
          />
        )}
        {page === "bugs" && (
          <BugsView
            testData={testData}
            selectedProject={selectedProject}
            onNavigate={setPage}
            activeRun={activeRun}
            apiBaseUrl={API_BASE_URL}
            token={token}
            onCancelRun={cancelActiveRun}
            onCompleteRun={(runData) => {
              loadRunResults(runData.id);
              loadHistory();
            }}
          />
        )}
        {page === "history" && (
          <RunHistory
            apiBaseUrl={API_BASE_URL}
            token={token}
            selectedProject={selectedProject}
            onLoadRun={loadRunResults}
            onViewActiveRun={(id) => {
              setActiveRunId(id);
              setPage("dashboard");
            }}
            onError={setError}
            onLogout={handleLogout}
          />
        )}
        {page === "usage" && (
          <UsageView
            apiBaseUrl={API_BASE_URL}
            token={token}
            currentUser={currentUser}
            onNavigate={setPage}
          />
        )}
        {page === "settings" && (
          <SettingsView
            currentUser={currentUser}
            theme={theme}
            onToggleTheme={handleToggleTheme}
            onNavigate={setPage}
            onLogout={handleLogout}
          />
        )}
        {page === "admin" && (
          <AdminDashboard
            apiBaseUrl={API_BASE_URL}
            token={token}
            currentUser={currentUser}
            onNavigate={setPage}
          />
        )}
      </main>
    </div>
  );
}
