import { useState, useMemo } from "react";
import { JsonDiffViewer } from "./JsonDiffViewer.jsx";
import { generateSafeCurl } from "./curlHelper.js";
import { RunProgress } from "./RunProgress.jsx";

const getMethodColor = (m = "") => {
  const method = m.toUpperCase();
  switch (method) {
    case "GET":
      return "var(--method-get)";
    case "POST":
      return "var(--method-post)";
    case "PUT":
      return "var(--method-put)";
    case "DELETE":
      return "var(--method-delete)";
    case "PATCH":
      return "var(--method-patch)";
    default:
      return "var(--text-muted)";
  }
};

const getMethodBg = (m = "") => {
  const method = m.toUpperCase();
  switch (method) {
    case "GET":
      return "var(--success-surface)";
    case "POST":
      return "var(--brand-surface)";
    case "PUT":
      return "var(--warning-surface)";
    case "DELETE":
      return "var(--danger-surface)";
    case "PATCH":
      return "rgba(139, 92, 246, 0.12)";
    default:
      return "var(--bg-subtle)";
  }
};

const getSeverityConfig = (s = "") => {
  const sev = s.toLowerCase();
  switch (sev) {
    case "critical":
      return { bg: "var(--danger-surface)", color: "var(--danger)", border: "var(--danger-border)" };
    case "high":
      return { bg: "var(--warning-surface)", color: "var(--warning)", border: "var(--warning-border)" };
    case "medium":
      return { bg: "var(--brand-surface)", color: "var(--brand-primary)", border: "var(--brand-border)" };
    case "low":
    default:
      return { bg: "var(--success-surface)", color: "var(--success)", border: "var(--success-border)" };
  }
};

export function ResultsView({
  testData,
  selectedProject,
  onNavigate,
  activeRun,
  apiBaseUrl,
  token,
  onCancelRun,
  onCompleteRun,
}) {
  const [filter, setFilter] = useState("ALL"); // "ALL" | "PASS" | "FAIL" | "AI" | "RULE"
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedTest, setSelectedTest] = useState(null);
  const [showMobileDetail, setShowMobileDetail] = useState(false);

  const results = useMemo(() => testData?.results || [], [testData?.results]);

  // Filtered test results
  const filtered = useMemo(() => {
    return results.filter((t) => {
      // Status & Category filters
      let matchesFilter = true;
      if (filter === "PASS") matchesFilter = t.status === "PASS";
      else if (filter === "FAIL") matchesFilter = t.status === "FAIL";
      else if (filter === "AI") matchesFilter = t.test_id?.startsWith("AI-");
      else if (filter === "RULE") matchesFilter = !t.test_id?.startsWith("AI-");

      // Search term
      const term = searchTerm.toLowerCase().trim();
      const matchesSearch =
        !term ||
        t.test_id?.toLowerCase().includes(term) ||
        t.endpoint?.toLowerCase().includes(term) ||
        t.method?.toLowerCase().includes(term) ||
        (t.failure_reason && t.failure_reason.toLowerCase().includes(term)) ||
        (t.description && t.description.toLowerCase().includes(term));

      return matchesFilter && matchesSearch;
    });
  }, [results, filter, searchTerm]);

  const handleSelectTest = (test) => {
    setSelectedTest(test);
    setShowMobileDetail(true);
  };

  const handleCloseDetail = () => {
    setSelectedTest(null);
    setShowMobileDetail(false);
  };

  const total = testData?.total ?? 0;
  const passed = testData?.passed ?? 0;
  const failed = testData?.failed ?? 0;
  const passRate = testData ? parseFloat(testData.pass_rate || 0) : 0;
  const aiCount = results.filter((t) => t.test_id?.startsWith("AI-")).length;
  const ruleCount = results.filter((t) => !t.test_id?.startsWith("AI-")).length;

  return (
    <div className="page fade-in" style={{ maxWidth: 1360, margin: "0 auto" }}>
      {/* ── Page Header & Stats Summary ── */}
      <div className="page-header" style={{ marginBottom: 18 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
              Test Execution Results
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
            Inspect status codes, schema validation assertions, and expected versus actual response bodies.
          </p>
        </div>

        {/* Execution Summary Chips */}
        {testData && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <div className="topbar-stat">
              <span style={{ color: "var(--text-primary)" }}>{total} Total</span>
            </div>
            <div className="topbar-stat">
              <span style={{ color: "var(--success)" }}>✓ {passed} Passed</span>
            </div>
            <div className="topbar-stat">
              <span style={{ color: "var(--danger)" }}>✗ {failed} Failed</span>
            </div>
            <div className="topbar-stat">
              <span style={{ color: "var(--brand-primary)", fontWeight: 700 }}>
                {passRate}% Pass Rate
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ── Active Background Execution Monitor ── */}
      {activeRun && (activeRun.status === "queued" || activeRun.status === "running") && (
        <div style={{ marginBottom: 20 }}>
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
        </div>
      )}

      {/* ── Empty State if No Data ── */}
      {!testData ? (
        !(activeRun && (activeRun.status === "queued" || activeRun.status === "running")) && (
          <div className="empty-page" style={{ padding: "60px 20px" }}>
            <div className="empty-icon">📋</div>
            <h3 style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>
              No Test Results Available
            </h3>
            <p style={{ color: "var(--text-secondary)", fontSize: 13.5, maxWidth: 440, margin: "0 auto 20px" }}>
              Execute a test run from the Dashboard or select a historical run from the Run History page to inspect diagnostics.
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn btn-primary" onClick={() => onNavigate("dashboard")}>
                Go to Dashboard
              </button>
              <button className="btn btn-ghost" onClick={() => onNavigate("history")}>
                View Run History
              </button>
            </div>
          </div>
        )
      ) : (
        <>
          {/* ── Search & Filter Controls Bar ── */}
          <div
            className="card"
            style={{
              marginBottom: 18,
              padding: "12px 18px",
              display: "flex",
              flexWrap: "wrap",
              gap: 12,
              alignItems: "center",
              justifyContent: "space-between",
              background: "var(--bg-subtle)",
            }}
          >
            {/* Search Input */}
            <div style={{ position: "relative", flex: 1, minWidth: 240, maxWidth: 420 }}>
              <input
                type="text"
                className="input"
                placeholder="Search by test ID, endpoint path, or method..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  height: 34,
                  padding: "6px 12px 6px 32px",
                  fontSize: 12.5,
                  background: "var(--bg-surface)",
                }}
              />
              <span
                style={{
                  position: "absolute",
                  left: 10,
                  top: "50%",
                  transform: "translateY(-50%)",
                  fontSize: 13,
                  color: "var(--text-muted)",
                }}
              >
                🔍
              </span>
              {searchTerm && (
                <button
                  type="button"
                  onClick={() => setSearchTerm("")}
                  style={{
                    position: "absolute",
                    right: 8,
                    top: "50%",
                    transform: "translateY(-50%)",
                    background: "none",
                    border: "none",
                    color: "var(--text-muted)",
                    cursor: "pointer",
                    fontSize: 12,
                  }}
                >
                  ✕
                </button>
              )}
            </div>

            {/* Filter Tabs */}
            <div className="filter-tabs" style={{ flexWrap: "wrap" }}>
              {[
                { id: "ALL", label: "All Tests", count: total },
                { id: "PASS", label: "✓ Passed", count: passed },
                { id: "FAIL", label: "✗ Failed", count: failed },
                { id: "AI", label: "🤖 AI-Generated", count: aiCount },
                { id: "RULE", label: "⚙️ Rule-Based", count: ruleCount },
              ].map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`filter-tab ${filter === f.id ? "active" : ""}`}
                  onClick={() => {
                    setFilter(f.id);
                    setSelectedTest(null);
                  }}
                  style={{ fontSize: 11.5, padding: "4px 10px" }}
                >
                  {f.label}
                  <span className="tab-count">{f.count}</span>
                </button>
              ))}
            </div>
          </div>

          {/* ── Two-Column Master-Detail Layout ── */}
          <div className="results-layout" style={{ gridTemplateColumns: "380px 1fr", gap: 18 }}>
            {/* Left Column: Test Suite List (Hidden on mobile when detail is open) */}
            <div
              className={`card results-list-card ${showMobileDetail ? "hide-on-mobile" : ""}`}
              style={{ padding: 12, display: "flex", flexDirection: "column" }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "4px 8px 10px",
                  borderBottom: "1px solid var(--border-default)",
                  marginBottom: 8,
                  fontSize: 11.5,
                  color: "var(--text-muted)",
                  fontWeight: 600,
                }}
              >
                <span>MATCHING TESTS ({filtered.length})</span>
                <span>STATUS / CODES</span>
              </div>

              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  maxHeight: "72vh",
                  overflowY: "auto",
                  paddingRight: 4,
                }}
                className="custom-scroll"
              >
                {filtered.length === 0 ? (
                  <div style={{ textAlign: "center", padding: "48px 16px", color: "var(--text-muted)" }}>
                    <div style={{ fontSize: 28, marginBottom: 8 }}>🔬</div>
                    <p style={{ margin: 0, fontSize: 13 }}>No tests match current filter.</p>
                  </div>
                ) : (
                  filtered.map((test) => {
                    const isSelected = selectedTest?.test_id === test.test_id;
                    const isAi = test.test_id?.startsWith("AI-");
                    const expSt = test.expected_status ?? test.expected?.status_code;
                    const actSt = test.actual_status ?? test.actual?.status_code;

                    return (
                      <div
                        key={test.test_id}
                        className={`result-row ${isSelected ? "selected" : ""} ${
                          test.status === "FAIL" ? "fail-row" : ""
                        }`}
                        onClick={() => handleSelectTest(test)}
                        style={{ padding: "10px 12px" }}
                      >
                        <div className="rr-left" style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span className="rr-id">{test.test_id}</span>
                            {isAi && <span className="ai-badge">AI</span>}
                          </div>
                          <span className="rr-ep" title={test.endpoint}>
                            {test.endpoint}
                          </span>
                        </div>

                        <div className="rr-right" style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span
                              className="rr-method"
                              style={{
                                background: getMethodBg(test.method),
                                color: getMethodColor(test.method),
                              }}
                            >
                              {test.method}
                            </span>
                            <span className={`rr-status ${test.status === "PASS" ? "pass" : "fail"}`}>
                              {test.status === "PASS" ? "✓" : "✗"} {test.status}
                            </span>
                          </div>
                          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--text-muted)" }}>
                            {expSt ?? "—"} → {actSt ?? "—"}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Right Column: Deep Test Inspection Panel */}
            <div className={`card detail-card ${!showMobileDetail ? "hide-on-mobile" : ""}`} style={{ padding: 22 }}>
              {selectedTest ? (
                <DetailPanel
                  test={selectedTest}
                  selectedProject={selectedProject}
                  onClose={handleCloseDetail}
                />
              ) : (
                <div className="empty-detail">
                  <div style={{ fontSize: 44, marginBottom: 12, opacity: 0.6 }}>🔬</div>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)", marginBottom: 6 }}>
                    Select a Test to Inspect
                  </h3>
                  <p style={{ color: "var(--text-secondary)", fontSize: 13, maxWidth: 320, textAlign: "center" }}>
                    Click any test row on the left to inspect HTTP status code comparisons, full JSON diffs, and AI defect analysis.
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Deep Test Diagnostics & JSON Diff Detail Panel
 */
function DetailPanel({ test, selectedProject, onClose }) {
  const [copiedCurl, setCopiedCurl] = useState(false);

  const expStatus = test.expected_status ?? test.expected?.status_code;
  const actStatus = test.actual_status ?? test.actual?.status_code;
  const statusMatch = expStatus === actStatus;
  const isAi = test.test_id?.startsWith("AI-");
  const sevConfig = getSeverityConfig(test.ai_analysis?.severity || "low");

  const safeCurl = useMemo(() => {
    return generateSafeCurl(test, selectedProject);
  }, [test, selectedProject]);

  const handleCopyCurl = () => {
    if (!safeCurl) return;
    navigator.clipboard.writeText(safeCurl);
    setCopiedCurl(true);
    setTimeout(() => setCopiedCurl(false), 2000);
  };

  const expBodyVal =
    test.expected_body ??
    test.expected_schema ??
    test.expected?.response_schema ??
    test.expected?.body;

  const actBodyVal = test.actual_body ?? test.actual?.body;

  return (
    <div className="detail-view fade-in">
      {/* Mobile Back Button */}
      <div className="show-on-mobile-only" style={{ marginBottom: 12 }}>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onClose}
          style={{ display: "flex", alignItems: "center", gap: 6 }}
        >
          ← Back to Test List
        </button>
      </div>

      {/* Header */}
      <div className="dv-header">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="dv-id">{test.test_id}</span>
            {isAi && <span className="ai-badge">AI Fuzzer</span>}
            <span
              style={{
                fontSize: 11,
                fontFamily: "var(--mono)",
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: "var(--r-xs)",
                background: getMethodBg(test.method),
                color: getMethodColor(test.method),
              }}
            >
              {test.method}
            </span>
          </div>
          <div className="dv-ep" style={{ fontFamily: "var(--mono)", fontSize: 13, marginTop: 6, color: "var(--text-primary)" }}>
            {test.endpoint}
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className={`pill ${test.status === "PASS" ? "pill-pass" : "pill-fail"}`}>
            {test.status === "PASS" ? "✓ PASSED" : "✗ FAILED"}
          </span>
          <button type="button" className="icon-btn" onClick={onClose} title="Close inspection panel">
            ✕
          </button>
        </div>
      </div>

      {/* Status Code Comparison Card */}
      <div className="status-compare" style={{ marginTop: 6 }}>
        <div className={`status-block ${statusMatch ? "ok" : "mismatch"}`}>
          <div className="sb-label">Expected Status Code</div>
          <div className="sb-code" style={{ color: "var(--success)" }}>
            {expStatus ?? "—"}
          </div>
        </div>

        <div className="status-arrow" style={{ fontSize: 20 }}>
          {statusMatch ? "✓" : "≠"}
        </div>

        <div className={`status-block ${statusMatch ? "ok" : "mismatch-right"}`}>
          <div className="sb-label">Actual Status Code</div>
          <div className="sb-code" style={{ color: statusMatch ? "var(--success)" : "var(--danger)" }}>
            {actStatus ?? "—"}
          </div>
        </div>
      </div>

      {/* Failure Reason Alert Banner */}
      {test.failure_reason && (
        <div className="failure-reason-block">
          <span className="fr-icon">⚠</span>
          <div>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>Assertion Failure Reason:</div>
            <div>{test.failure_reason}</div>
          </div>
        </div>
      )}

      {/* Interactive JSON Diff Viewer (Part B) */}
      <div style={{ marginTop: 4 }}>
        <div className="section-label" style={{ marginBottom: 8 }}>
          Payload & Schema Validation Diff
        </div>
        <JsonDiffViewer expectedBody={expBodyVal} actualBody={actBodyVal} />
      </div>

      {/* AI Failure Analysis Block (if available) */}
      {test.ai_analysis && (
        <div
          className="ai-analysis-block"
          style={{
            borderColor: sevConfig.border,
            background: "linear-gradient(135deg, rgba(139,92,246,0.06), var(--bg-surface))",
            marginTop: 4,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <span className="aa-title" style={{ margin: 0 }}>
              🤖 AI Failure & Root-Cause Intelligence
            </span>
            <span
              className="sev-pill"
              style={{
                background: sevConfig.bg,
                color: sevConfig.color,
                border: `1px solid ${sevConfig.border}`,
              }}
            >
              {test.ai_analysis.severity || "Defect"}
            </span>
          </div>

          <div className="aa-grid">
            <div className="aa-item">
              <div className="aa-key">Defect Summary</div>
              <div className="aa-val">{test.ai_analysis.summary}</div>
            </div>
            <div className="aa-item">
              <div className="aa-key">Identified Root Cause</div>
              <div className="aa-val">{test.ai_analysis.possible_cause}</div>
            </div>
            <div className="aa-item" style={{ gridColumn: "span 2" }}>
              <div className="aa-key">Recommended Remediation</div>
              <div className="aa-val">{test.ai_analysis.recommendation}</div>
            </div>
          </div>
        </div>
      )}

      {/* Safe Reproduction cURL Command (Part D) */}
      {safeCurl && (
        <div style={{ marginTop: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <span className="section-label" style={{ margin: 0 }}>
              Safe Reproduction cURL Command
            </span>
            <button
              type="button"
              className="shortcut-btn"
              onClick={handleCopyCurl}
              style={{ fontSize: 11 }}
            >
              {copiedCurl ? "✓ Command Copied!" : "Copy cURL"}
            </button>
          </div>
          <pre
            className="code-pre custom-scroll"
            style={{
              padding: "10px 14px",
              fontSize: 11.5,
              background: "var(--bg-subtle)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-sm)",
            }}
          >
            {safeCurl}
          </pre>
          <span style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 4, display: "block" }}>
            🔒 Note: Sensitive API secrets and Bearer tokens are omitted from this command for security.
          </span>
        </div>
      )}
    </div>
  );
}
