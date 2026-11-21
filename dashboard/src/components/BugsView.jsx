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
      return { bg: "var(--danger-surface)", color: "var(--danger)", border: "var(--danger-border)", label: "Critical" };
    case "high":
      return { bg: "var(--warning-surface)", color: "var(--warning)", border: "var(--warning-border)", label: "High" };
    case "medium":
      return { bg: "var(--brand-surface)", color: "var(--brand-primary)", border: "var(--brand-border)", label: "Medium" };
    case "low":
    default:
      return { bg: "var(--success-surface)", color: "var(--success)", border: "var(--success-border)", label: "Low" };
  }
};

export function BugsView({
  testData,
  selectedProject,
  onNavigate,
  activeRun,
  apiBaseUrl,
  token,
  onCancelRun,
  onCompleteRun,
}) {
  const [severityFilter, setSeverityFilter] = useState("ALL"); // "ALL" | "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
  const [searchTerm, setSearchTerm] = useState("");
  const [expandedTests, setExpandedTests] = useState({});
  const [copiedCurls, setCopiedCurls] = useState({});

  const allFailures = useMemo(() => {
    return testData ? testData.results.filter((t) => t.status === "FAIL") : [];
  }, [testData]);

  // Real severity counts
  const severityCounts = useMemo(() => {
    const counts = { total: allFailures.length, critical: 0, high: 0, medium: 0, low: 0, noAi: 0 };
    allFailures.forEach((t) => {
      const sev = t.bug_report?.severity?.toLowerCase() || t.ai_analysis?.severity?.toLowerCase();
      if (sev === "critical") counts.critical += 1;
      else if (sev === "high") counts.high += 1;
      else if (sev === "medium") counts.medium += 1;
      else if (sev === "low") counts.low += 1;
      else counts.noAi += 1;
    });
    return counts;
  }, [allFailures]);

  // Filtered failures
  const filteredFailures = useMemo(() => {
    return allFailures.filter((t) => {
      const sev = (t.bug_report?.severity || t.ai_analysis?.severity || "low").toUpperCase();
      let matchesSev = true;
      if (severityFilter !== "ALL") {
        matchesSev = sev === severityFilter;
      }

      const term = searchTerm.toLowerCase().trim();
      const matchesSearch =
        !term ||
        t.test_id?.toLowerCase().includes(term) ||
        t.endpoint?.toLowerCase().includes(term) ||
        t.method?.toLowerCase().includes(term) ||
        (t.failure_reason && t.failure_reason.toLowerCase().includes(term)) ||
        (t.bug_report?.summary && t.bug_report.summary.toLowerCase().includes(term)) ||
        (t.bug_report?.possible_cause && t.bug_report.possible_cause.toLowerCase().includes(term));

      return matchesSev && matchesSearch;
    });
  }, [allFailures, severityFilter, searchTerm]);

  const toggleExpand = (testId) => {
    setExpandedTests((prev) => ({
      ...prev,
      [testId]: !prev[testId],
    }));
  };

  const handleCopyCurl = (test) => {
    const curl = generateSafeCurl(test, selectedProject);
    if (!curl) return;
    navigator.clipboard.writeText(curl);
    setCopiedCurls((prev) => ({ ...prev, [test.test_id]: true }));
    setTimeout(() => {
      setCopiedCurls((prev) => ({ ...prev, [test.test_id]: false }));
    }, 2000);
  };

  if (!testData) {
    return (
      <div className="page fade-in" style={{ maxWidth: 1200, margin: "0 auto" }}>
        <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800, marginBottom: 16 }}>
          Bug Reports & Defect Intelligence
        </h1>

        {activeRun && (activeRun.status === "queued" || activeRun.status === "running") ? (
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
        ) : (
          <div className="empty-page" style={{ padding: "60px 20px", marginTop: 20 }}>
            <div className="empty-icon">🐛</div>
            <h3 style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>
              No Failure Data Loaded
            </h3>
            <p style={{ color: "var(--text-secondary)", fontSize: 13.5, maxWidth: 440, margin: "0 auto 20px" }}>
              Execute a test run from the Dashboard to see automated defect reports and AI failure root-cause analysis.
            </p>
            <button className="btn btn-primary" onClick={() => onNavigate("dashboard")}>
              Go to Dashboard
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="page fade-in" style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* ── Page Header & Severity Counters ── */}
      <div className="page-header" style={{ marginBottom: 18 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
              Defect Intelligence & Bug Reports
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
            Triaged failure diagnostics, automated root-cause explanations, and actionable remediation guidance.
          </p>
        </div>

        {/* Severity Metrics Chips */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <div className="topbar-stat">
            <span style={{ color: "var(--danger)", fontWeight: 700 }}>
              {severityCounts.total} Total Failures
            </span>
          </div>
          <div className="topbar-stat">
            <span style={{ color: "var(--danger)" }}>
              {severityCounts.critical} Critical
            </span>
          </div>
          <div className="topbar-stat">
            <span style={{ color: "var(--warning)" }}>
              {severityCounts.high} High
            </span>
          </div>
          <div className="topbar-stat">
            <span style={{ color: "var(--brand-primary)" }}>
              {severityCounts.medium} Medium
            </span>
          </div>
          <div className="topbar-stat">
            <span style={{ color: "var(--success)" }}>
              {severityCounts.low} Low
            </span>
          </div>
        </div>
      </div>

      {/* ── All Tests Passed Celebration Card ── */}
      {allFailures.length === 0 ? (
        <div
          className="empty-page"
          style={{
            padding: "50px 24px",
            background: "linear-gradient(135deg, var(--success-surface) 0%, var(--bg-surface) 100%)",
            border: "1px solid var(--success-border)",
          }}
        >
          <div style={{ fontSize: 52, marginBottom: 12 }}>🎉</div>
          <h2 style={{ color: "var(--success)", fontSize: 20, fontWeight: 800, margin: "0 0 6px" }}>
            All Tests Passed Successfully!
          </h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13.5, maxWidth: 440, margin: 0, textAlign: "center" }}>
            Zero status code mismatches, schema validation failures, or unhandled exceptions detected in the current test run.
          </p>
        </div>
      ) : (
        <>
          {/* ── Filter & Search Toolbar ── */}
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
                placeholder="Search defects by endpoint, summary, or root cause..."
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

            {/* Severity Filter Tabs */}
            <div className="filter-tabs" style={{ flexWrap: "wrap" }}>
              {[
                { id: "ALL", label: "All Severities", count: severityCounts.total },
                { id: "CRITICAL", label: "Critical", count: severityCounts.critical },
                { id: "HIGH", label: "High", count: severityCounts.high },
                { id: "MEDIUM", label: "Medium", count: severityCounts.medium },
                { id: "LOW", label: "Low", count: severityCounts.low },
              ].map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`filter-tab ${severityFilter === f.id ? "active" : ""}`}
                  onClick={() => setSeverityFilter(f.id)}
                  style={{ fontSize: 11.5, padding: "4px 10px" }}
                >
                  {f.label}
                  <span className="tab-count">{f.count}</span>
                </button>
              ))}
            </div>
          </div>

          {/* ── Defect Cards Grid ── */}
          {filteredFailures.length === 0 ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
              No defects match the selected filters.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {filteredFailures.map((test) => {
                const br = test.bug_report || test.ai_analysis;
                const hasAi = Boolean(br);
                const sevConfig = getSeverityConfig(br?.severity || "low");
                const isExpanded = Boolean(expandedTests[test.test_id]);
                const expSt = test.expected_status ?? test.expected?.status_code;
                const actSt = test.actual_status ?? test.actual?.status_code;
                const statusMatch = expSt != null && actSt != null && expSt === actSt;

                const expBodyVal =
                  test.expected_body ??
                  test.expected_schema ??
                  test.expected?.response_schema ??
                  test.expected?.body;

                const actBodyVal = test.actual_body ?? test.actual?.body;

                const safeCurl = generateSafeCurl(test, selectedProject);

                return (
                  <div
                    key={test.test_id}
                    className="card"
                    style={{
                      padding: 20,
                      borderColor: isExpanded ? sevConfig.color : "var(--border-default)",
                      borderLeft: `4px solid ${sevConfig.color}`,
                      transition: "var(--t)",
                      boxShadow: isExpanded ? "var(--shadow-md)" : "var(--shadow-sm)",
                    }}
                  >
                    {/* Defect Card Header */}
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        gap: 12,
                        cursor: "pointer",
                      }}
                      onClick={() => toggleExpand(test.test_id)}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                          <span
                            className="sev-pill"
                            style={{
                              background: sevConfig.bg,
                              color: sevConfig.color,
                              border: `1px solid ${sevConfig.border}`,
                            }}
                          >
                            {sevConfig.label.toUpperCase()}
                          </span>

                          <span style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 700, color: "var(--text-primary)" }}>
                            {test.test_id}
                          </span>

                          {hasAi ? (
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 700,
                                padding: "1px 6px",
                                borderRadius: "var(--r-xs)",
                                background: "rgba(139, 92, 246, 0.15)",
                                color: "#8b5cf6",
                                border: "1px solid rgba(139, 92, 246, 0.3)",
                              }}
                            >
                              🤖 AI Analyzed
                            </span>
                          ) : (
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 600,
                                padding: "1px 6px",
                                borderRadius: "var(--r-xs)",
                                background: "var(--bg-subtle)",
                                color: "var(--text-muted)",
                                border: "1px solid var(--border-default)",
                              }}
                            >
                              Manual Triage
                            </span>
                          )}
                        </div>

                        {/* Endpoint Path */}
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                          <span
                            style={{
                              fontFamily: "var(--mono)",
                              fontSize: 10.5,
                              fontWeight: 700,
                              padding: "2px 6px",
                              borderRadius: "var(--r-xs)",
                              background: getMethodBg(test.method),
                              color: getMethodColor(test.method),
                            }}
                          >
                            {test.method}
                          </span>
                          <span style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--text-primary)", fontWeight: 600 }}>
                            {test.endpoint}
                          </span>
                        </div>

                        {/* Summary / Cause Preview */}
                        <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                          {br?.summary || test.failure_reason || "Assertion failure encountered."}
                        </p>
                      </div>

                      {/* Expand / Collapse Control */}
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 600,
                            color: "var(--brand-primary)",
                          }}
                        >
                          {isExpanded ? "▲ Collapse" : "▼ Inspect Defect"}
                        </span>
                      </div>
                    </div>

                    {/* ── Expanded Defect Inspection Accordion ── */}
                    {isExpanded && (
                      <div
                        className="fade-in"
                        style={{
                          marginTop: 18,
                          paddingTop: 16,
                          borderTop: "1px solid var(--border-default)",
                          display: "flex",
                          flexDirection: "column",
                          gap: 16,
                        }}
                      >
                        {/* Status Code Comparison Card */}
                        <div className="status-compare">
                          <div className={`status-block ${statusMatch ? "ok" : "mismatch"}`}>
                            <div className="sb-label">Expected Status Code</div>
                            <div className="sb-code" style={{ color: "var(--success)" }}>
                              {expSt ?? "—"}
                            </div>
                          </div>

                          <div className="status-arrow" style={{ fontSize: 20 }}>
                            {statusMatch ? "✓" : "≠"}
                          </div>

                          <div className={`status-block ${statusMatch ? "ok" : "mismatch-right"}`}>
                            <div className="sb-label">Actual Status Code</div>
                            <div className="sb-code" style={{ color: statusMatch ? "var(--success)" : "var(--danger)" }}>
                              {actSt ?? "—"}
                            </div>
                          </div>
                        </div>

                        {/* Validation Checks */}
                        <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-default)" }}>
                          <div className="section-label" style={{ marginBottom: 8 }}>
                            Automated Verification Checks
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12.5 }}>
                              <span style={{ color: "var(--text-secondary)" }}>HTTP Status Code Verification</span>
                              <span style={{ fontWeight: 700, color: statusMatch ? "var(--success)" : "var(--danger)" }}>
                                {statusMatch ? "✅ PASS" : "❌ FAIL"}
                              </span>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12.5 }}>
                              <span style={{ color: "var(--text-secondary)" }}>Response Body Schema Verification</span>
                              <span style={{ fontWeight: 700, color: test.failure_reason?.includes("schema") || test.failure_reason?.includes("body") ? "var(--danger)" : "var(--text-muted)" }}>
                                {test.failure_reason?.includes("schema") || test.failure_reason?.includes("body") ? "❌ FAIL (Mismatch)" : "— Evaluated"}
                              </span>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12.5 }}>
                              <span style={{ color: "var(--text-secondary)" }}>Overall Suite Verdict</span>
                              <span style={{ fontWeight: 700, color: "var(--danger)" }}>
                                ❌ FAILED
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* Root Cause & Remediation (AI Intelligence) */}
                        {hasAi ? (
                          <div
                            style={{
                              background: "linear-gradient(135deg, rgba(139,92,246,0.06), var(--bg-surface))",
                              padding: 16,
                              borderRadius: "var(--r-md)",
                              border: "1px solid var(--border-default)",
                            }}
                          >
                            <div className="section-label" style={{ color: "var(--brand-primary)", marginBottom: 10 }}>
                              🤖 AI Failure Root-Cause Analysis
                            </div>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                              <div>
                                <div className="bce-label">Possible Root Cause</div>
                                <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                                  {br.possible_cause}
                                </p>
                              </div>
                              <div>
                                <div className="bce-label">Recommended Remediation</div>
                                <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                                  {br.recommendation}
                                </p>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <div
                            style={{
                              padding: "12px 16px",
                              background: "var(--bg-subtle)",
                              borderRadius: "var(--r-sm)",
                              border: "1px solid var(--border-default)",
                              fontSize: 12.5,
                              color: "var(--text-muted)",
                            }}
                          >
                            ℹ️ AI failure analysis was not generated for this test run. Inspect the expected versus actual payload diff below.
                          </div>
                        )}

                        {/* Failure Reason */}
                        {test.failure_reason && (
                          <div>
                            <div className="bce-label">Exact Assertion Failure Reason</div>
                            <div
                              style={{
                                marginTop: 4,
                                padding: "10px 14px",
                                background: "var(--danger-surface)",
                                border: "1px solid var(--danger-border)",
                                borderRadius: "var(--r-sm)",
                                fontSize: 12.5,
                                color: "var(--danger)",
                                lineHeight: 1.5,
                              }}
                            >
                              {test.failure_reason}
                            </div>
                          </div>
                        )}

                        {/* Interactive JSON Diff Viewer */}
                        <div>
                          <div className="section-label" style={{ marginBottom: 6 }}>
                            Response Payload Comparison
                          </div>
                          <JsonDiffViewer expectedBody={expBodyVal} actualBody={actBodyVal} />
                        </div>

                        {/* Copy Reproduction cURL */}
                        {safeCurl && (
                          <div style={{ marginTop: 4 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                              <span className="section-label" style={{ margin: 0 }}>
                                Reproduction cURL Command
                              </span>
                              <button
                                type="button"
                                className="shortcut-btn"
                                onClick={() => handleCopyCurl(test)}
                                style={{ fontSize: 11 }}
                              >
                                {copiedCurls[test.test_id] ? "✓ Copied!" : "Copy cURL"}
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
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
