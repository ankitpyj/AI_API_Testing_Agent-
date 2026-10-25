import { useState, useEffect, useRef, useCallback } from "react";
import "./App.css";

/* ══════════════════════════════════════════════════════
   UTILITIES
══════════════════════════════════════════════════════ */
const parseJsonField = (v) => {
  if (v == null) return null;
  if (typeof v === "object") return v;
  try { return JSON.parse(v); } catch { return v; }
};

const methodColor = { GET: "#10b981", POST: "#3b82f6", PUT: "#f59e0b", DELETE: "#f43f5e", PATCH: "#8b5cf6" };
const getMethodColor = (m = "") => methodColor[m.toUpperCase()] || "#8892a4";

const severityConfig = {
  critical: { bg: "rgba(244,63,94,0.15)",  color: "#f43f5e", border: "rgba(244,63,94,0.3)" },
  high:     { bg: "rgba(245,158,11,0.15)", color: "#f59e0b", border: "rgba(245,158,11,0.3)" },
  medium:   { bg: "rgba(59,130,246,0.15)", color: "#3b82f6", border: "rgba(59,130,246,0.3)" },
  low:      { bg: "rgba(16,185,129,0.15)", color: "#10b981", border: "rgba(16,185,129,0.3)" },
};
const getSeverity = (s = "") => severityConfig[s.toLowerCase()] || severityConfig.low;

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
   PAGE: DASHBOARD (Overview)
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
}){
  const total    = testData?.total    ?? 0;
  const passed   = testData?.passed   ?? 0;
  const failed   = testData?.failed   ?? 0;
  const passRate = testData ? parseFloat(testData.pass_rate) : 0;
  const aiCount  = testData ? testData.results.filter(t => t.test_id?.startsWith("AI-")).length : 0;
  const ruleCount= testData ? testData.results.filter(t => !t.test_id?.startsWith("AI-")).length : 0;
  const bugsFound= testData ? testData.results.filter(t => t.bug_report).length : 0;

  const statCards = [
    { label:"Total Tests",    value: total,    icon:"📊", color:"blue",   suffix:"" },
    { label:"Passed",         value: passed,   icon:"✅", color:"green",  suffix:"" },
    { label:"Failed",         value: failed,   icon:"❌", color:"rose",   suffix:"" },
    { label:"Pass Rate",      value: passRate, icon:"🎯", color:"violet", suffix:"%" },
  ];

  return (
    <div className="page fade-in">
      {/* Welcome Banner */}
      <div className="welcome-banner">
        <div>
          <h2 className="page-title">Good evening, Engineer 👋</h2>
          <p className="page-sub">Here's your API quality overview. {testData ? `Last run: ${total} tests executed.` : "No tests run yet."}</p>
        </div>
        <button className="btn btn-primary" onClick={onRunTests} disabled={loading}>
          {loading ? <><div className="spinner"/>Running…</> : <>▶ Run Tests</>}
        </button>
      </div>

      {/* Target API Configuration */} 
      <div className="stat-card" style={{ marginBottom: 24, padding: 24 }}> <h3 style={{ marginTop: 0 }}>Target API Configuration</h3> <p className="page-sub"> Enter the API you want the agent to test. </p> <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", marginTop: 20, }}> <label style={{ display: "grid", gap: 8 }}> <span>Target Base URL</span> <input type="url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.example.com" style={{ width: "100%", padding: 12, borderRadius: 8 }} /> </label> <label style={{ display: "grid", gap: 8 }}> <span>OpenAPI Specification URL</span> <input type="url" value={openapiUrl} onChange={e => setOpenapiUrl(e.target.value)} placeholder="https://api.example.com/openapi.json" style={{ width: "100%", padding: 12, borderRadius: 8 }} /> </label> </div> <p className="page-sub" style={{ marginTop: 12 }}> For your current demo, keep the default URLs. The API specification must describe the target API you are testing. </p> </div> {/* Stat cards */} <div className="stats-grid"></div>



      {/* Stat cards */}
      <div className="stats-grid">
        {statCards.map((c, i) => (
          <div key={c.label} className={`stat-card ${c.color}`} style={{ animationDelay: `${i * 0.07}s` }}>
            <div className={`stat-icon ${c.color}`}>{c.icon}</div>
            <div className="stat-label">{c.label}</div>
            <div className="stat-value">
              {testData ? <AnimatedNumber value={c.value} suffix={c.suffix}/> : <span style={{color:"var(--text-muted)"}}>—</span>}
            </div>
            {c.label === "Pass Rate" && (
              <div className="progress-bar-wrap">
                <div className="progress-bar-fill" style={{ width: testData ? `${passRate}%` : "0%" }}/>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Two-col: donut + AI breakdown */}
      <div className="grid-2col" style={{ marginBottom: 24 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Result Distribution</span>
            <span className="card-badge blue">Live</span>
          </div>
          <div style={{ marginTop: 12 }}>
            <DonutChart passed={passed} failed={failed} total={total}/>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Test Generation Mix</span>
          </div>
          <div style={{ marginTop: 16, display:"flex", flexDirection:"column", gap:16 }}>
            <div className="gen-bar-row">
              <span className="gen-bar-label">⚙️ Rule-Based</span>
              <div className="gen-bar-track">
                <div className="gen-bar-fill blue" style={{ width: total > 0 ? `${(ruleCount/total)*100}%` : "0%" }}/>
              </div>
              <span className="gen-bar-num">{ruleCount}</span>
            </div>
            <div className="gen-bar-row">
              <span className="gen-bar-label">🤖 AI-Generated</span>
              <div className="gen-bar-track">
                <div className="gen-bar-fill violet" style={{ width: total > 0 ? `${(aiCount/total)*100}%` : "0%" }}/>
              </div>
              <span className="gen-bar-num">{aiCount}</span>
            </div>
            <div className="gen-bar-row">
              <span className="gen-bar-label">🐛 Bugs Found</span>
              <div className="gen-bar-track">
                <div className="gen-bar-fill rose" style={{ width: total > 0 ? `${(bugsFound/total)*100}%` : "0%" }}/>
              </div>
              <span className="gen-bar-num">{bugsFound}</span>
            </div>
          </div>

          {/* Quick nav shortcuts */}
          <div style={{ marginTop: 28, display:"flex", gap:10, flexWrap:"wrap" }}>
            <button className="shortcut-btn" onClick={() => onNavigate("results")}>View Results →</button>
            <button className="shortcut-btn rose" onClick={() => onNavigate("bugs")}>View Bugs →</button>
          </div>
        </div>
      </div>

      {/* Recent failures quick view */}
      {testData && failed > 0 && (
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">⚠ Recent Failures</span>
            <button className="shortcut-btn rose" onClick={() => onNavigate("bugs")} style={{ fontSize:11 }}>See all bugs</button>
          </div>
          <div style={{ marginTop: 14, display:"flex", flexDirection:"column", gap: 8 }}>
            {testData.results.filter(t => t.status === "FAIL").slice(0, 4).map(t => (
              <div key={t.test_id} className="quick-fail-row">
                <span className="qf-id">{t.test_id}</span>
                <span className="qf-method" style={{ color: getMethodColor(t.method) }}>{t.method}</span>
                <span className="qf-ep">{t.endpoint}</span>
                <span className="qf-reason">{t.failure_reason?.slice(0,60) || "—"}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!testData && (
        <div className="empty-cta">
          <div className="empty-cta-icon">🚀</div>
          <h3>Ready to test your API?</h3>
          <p>Click <strong>Run Tests</strong> to execute the full test suite — rule-based and AI-generated.</p>
          <button className="btn btn-primary" onClick={onRunTests} disabled={loading} style={{ marginTop: 20 }}>
            {loading ? <><div className="spinner"/>Running…</> : <>▶ Run Tests Now</>}
          </button>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   PAGE: TEST RESULTS
══════════════════════════════════════════════════════ */
function ResultsPage({ testData }) {
  const [filter, setFilter] = useState("ALL");
  const [selected, setSelected] = useState(null);

  const filtered = testData
    ? testData.results.filter(t => filter === "ALL" || t.status === filter)
    : [];

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Test Results</h2>
          <p className="page-sub">Click any row to inspect the full request/response diff</p>
        </div>
        <div className="filter-tabs">
          {["ALL","PASS","FAIL"].map(f => (
            <button key={f} className={`filter-tab ${filter===f?"active":""}`} onClick={() => { setFilter(f); setSelected(null); }}>
              {f==="ALL"?"All Tests":f==="PASS"?"✓ Passed":"✗ Failed"}
              {testData && (
                <span className="tab-count">
                  {f==="ALL" ? testData.total : f==="PASS" ? testData.passed : testData.failed}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {!testData ? (
        <div className="empty-page">
          <div className="empty-icon">📋</div>
          <p>No test data yet. Run tests from the Dashboard.</p>
        </div>
      ) : (
        <div className="results-layout">
          {/* Left: test list */}
          <div className="card results-list-card">
            <div style={{ display:"flex", flexDirection:"column", gap:4, maxHeight:"70vh", overflowY:"auto", paddingRight:4 }} className="custom-scroll">
              {filtered.length === 0 ? (
                <div style={{ textAlign:"center", padding:"40px 20px", color:"var(--text-muted)" }}>
                  No {filter.toLowerCase() === "all" ? "" : filter.toLowerCase()} tests found.
                </div>
              ) : filtered.map(test => (
                <div
                  key={test.test_id}
                  className={`result-row ${selected?.test_id === test.test_id ? "selected" : ""} ${test.status === "FAIL" ? "fail-row" : ""}`}
                  onClick={() => setSelected(test)}
                >
                  <div className="rr-left">
                    <span className="rr-id">{test.test_id}{test.test_id?.startsWith("AI-") && <span className="ai-badge">AI</span>}</span>
                    <span className="rr-ep">{test.method} {test.endpoint}</span>
                  </div>
                  <div className="rr-right">
                    <span className="rr-method" style={{ background: `${getMethodColor(test.method)}20`, color: getMethodColor(test.method) }}>
                      {test.method}
                    </span>
                    <span className={`rr-status ${test.status === "PASS" ? "pass" : "fail"}`}>
                      {test.status === "PASS" ? "✓" : "✗"} {test.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: detail pane */}
          <div className="card detail-card">
            {selected ? (
              <TestDetailView test={selected} onClose={() => setSelected(null)}/>
            ) : (
              <div className="empty-detail">
                <div style={{ fontSize:40, marginBottom:12 }}>🔬</div>
                <p style={{ color:"var(--text-muted)", fontSize:14 }}>Select a test row to inspect</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function TestDetailView({ test, onClose }) {
  const expStatus = test.expected_status ?? test.expected?.status_code;
  const actStatus = test.actual_status   ?? test.actual?.status_code;
  const statusMatch = expStatus === actStatus;
  const sev = getSeverity(test.ai_analysis?.severity);

  return (
    <div className="detail-view fade-in">
      {/* header */}
      <div className="dv-header">
        <div>
          <div className="dv-id">{test.test_id}{test.test_id?.startsWith("AI-") && <span className="ai-badge" style={{ marginLeft:8 }}>AI</span>}</div>
          <div className="dv-ep">{test.method} {test.endpoint}</div>
        </div>
        <div style={{ display:"flex", gap:8, alignItems:"center" }}>
          <span className={`pill ${test.status==="PASS"?"pill-pass":"pill-fail"}`}>{test.status==="PASS"?"✓ PASS":"✗ FAIL"}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
      </div>

      {/* Status comparison */}
      <div className="status-compare">
        <div className={`status-block ${statusMatch ? "ok" : "mismatch"}`}>
          <div className="sb-label">Expected Status</div>
          <div className="sb-code">{expStatus ?? "—"}</div>
        </div>
        <div className="status-arrow">{statusMatch ? "✓" : "≠"}</div>
        <div className={`status-block ${statusMatch ? "ok" : "mismatch-right"}`}>
          <div className="sb-label">Actual Status</div>
          <div className="sb-code">{actStatus ?? "—"}</div>
        </div>
      </div>

      {/* Body diff */}
      <div className="body-diff">
        <div className="diff-block">
          <div className="diff-label">📤 Expected Body</div>
          <pre className="code-pre">{JSON.stringify(parseJsonField(test.expected_body ?? test.expected?.body), null, 2) || "—"}</pre>
        </div>
        <div className="diff-block">
          <div className="diff-label">📥 Actual Body</div>
          <pre className="code-pre">{JSON.stringify(parseJsonField(test.actual_body ?? test.actual?.body), null, 2) || "—"}</pre>
        </div>
      </div>

      {/* Failure reason */}
      {test.failure_reason && (
        <div className="failure-reason-block">
          <span className="fr-icon">⚠</span>
          <span>{test.failure_reason}</span>
        </div>
      )}

      {/* AI Analysis */}
      {test.ai_analysis && (
        <div className="ai-analysis-block" style={{ borderColor: sev.border }}>
          <div className="aa-title">🤖 AI Failure Analysis</div>
          <div className="aa-grid">
            <div className="aa-item">
              <div className="aa-key">Summary</div>
              <div className="aa-val">{test.ai_analysis.summary}</div>
            </div>
            <div className="aa-item">
              <div className="aa-key">Root Cause</div>
              <div className="aa-val">{test.ai_analysis.possible_cause}</div>
            </div>
            <div className="aa-item">
              <div className="aa-key">Severity</div>
              <div className="aa-val">
                <span className="sev-pill" style={{ background: sev.bg, color: sev.color, border:`1px solid ${sev.border}` }}>
                  {test.ai_analysis.severity}
                </span>
              </div>
            </div>
            <div className="aa-item">
              <div className="aa-key">Recommendation</div>
              <div className="aa-val">{test.ai_analysis.recommendation}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   PAGE: BUG REPORTS
══════════════════════════════════════════════════════ */
function BugsPage({ testData }) {
  const [selected, setSelected] = useState(null);

  const failedWithBugs = testData
    ? testData.results.filter(t => t.status === "FAIL")
    : [];

  const bugsOnly = failedWithBugs.filter(t => t.bug_report);
  const failsNoBug = failedWithBugs.filter(t => !t.bug_report);

  if (!testData) return (
    <div className="page fade-in">
      <h2 className="page-title">Bug Reports</h2>
      <div className="empty-page"><div className="empty-icon">🐛</div><p>Run tests first to see bug reports.</p></div>
    </div>
  );

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Bug Reports</h2>
          <p className="page-sub">{bugsOnly.length} AI-analyzed bugs · {failsNoBug.length} unanalyzed failures</p>
        </div>
        <div style={{ display:"flex", gap:12 }}>
          <div className="mini-stat-chip rose">{failedWithBugs.length} Failures</div>
          <div className="mini-stat-chip violet">{bugsOnly.length} Reports</div>
        </div>
      </div>

      {failedWithBugs.length === 0 ? (
        <div className="empty-page">
          <div className="empty-icon" style={{ fontSize:56 }}>🎉</div>
          <h3 style={{ color:"var(--accent-green)", margin:"12px 0 8px" }}>All Tests Passed!</h3>
          <p style={{ color:"var(--text-muted)" }}>No failures detected in this test run.</p>
        </div>
      ) : (
        <div style={{ display:"flex", flexDirection:"column", gap: 16 }}>

          {/* Bug cards grid */}
          {bugsOnly.length > 0 && (
            <>
              <div className="section-label">🤖 AI-Analyzed Bug Reports</div>
              <div className="bugs-grid">
                {bugsOnly.map(test => {
                  const br = test.bug_report;
                  const sev = getSeverity(br.severity);
                  const isSelected = selected?.test_id === test.test_id;
                  return (
                    <div
                      key={test.test_id}
                      className={`bug-card ${isSelected ? "bug-card-selected" : ""}`}
                      style={{ borderColor: isSelected ? sev.color : "var(--border)" }}
                      onClick={() => setSelected(isSelected ? null : test)}
                    >
                      <div className="bc-header">
                        <span className="bc-id">{br.bug_id || "BUG"}</span>
                        <span className="sev-pill" style={{ background:sev.bg, color:sev.color, border:`1px solid ${sev.border}` }}>{br.severity}</span>
                      </div>
                      <div className="bc-test">{test.test_id}</div>
                      <div className="bc-endpoint">
                        <span style={{ color: getMethodColor(test.method), fontSize:11, fontWeight:700 }}>{test.method}</span>
                        {" "}{test.endpoint}
                      </div>
                      <div className="bc-summary">{br.summary}</div>
                      <div className="bc-footer">
                        <span>{isSelected ? "▲ Collapse" : "▼ View Details"}</span>
                        <span style={{ color:"var(--text-muted)", fontSize:11 }}>{br.status || "OPEN"}</span>
                      </div>

                      {isSelected && (() => {
                        const expSt  = test.expected_status ?? test.expected?.status_code;
                        const actSt  = test.actual_status   ?? test.actual?.status_code;
                        const statusPass = expSt != null && actSt != null && expSt === actSt;
                        const bodyFail   = test.failure_reason
                          ? /body|content|response|field|key|value|mismatch|schema/i.test(test.failure_reason)
                          : false;
                        const bodyPass   = !bodyFail;

                        const checks = [
                          { label: "Status Code Check",   pass: statusPass },
                          { label: "Response Body Check", pass: bodyPass   },
                          { label: "Overall Test",        pass: false       },
                        ];

                        return (
                          <div className="bc-expanded fade-in">
                            {/* ── Individual Checks ── */}
                            <div className="bce-section">
                              <div className="bce-label">Checks</div>
                              <div className="bc-checks">
                                {checks.map(({ label, pass }) => (
                                  <div key={label} className="bc-check-row">
                                    <span className="bc-check-label">{label}</span>
                                    <span className={`bc-check-badge ${pass ? "pass" : "fail"}`}>
                                      {pass ? "✅ PASS" : "❌ FAIL"}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>

                            <div className="bce-section">
                              <div className="bce-label">Root Cause</div>
                              <div className="bce-val">{br.possible_cause}</div>
                            </div>
                            <div className="bce-section">
                              <div className="bce-label">Recommendation</div>
                              <div className="bce-val">{br.recommendation}</div>
                            </div>
                            <div className="bce-section">
                              <div className="bce-label">Failure Reason</div>
                              <div className="bce-val">{test.failure_reason || "—"}</div>
                            </div>
                            <div className="body-diff" style={{ marginTop:12 }}>
                              <div className="diff-block">
                                <div className="diff-label">Expected Status</div>
                                <div className="sb-code" style={{ fontSize:22, marginTop:6, color:"var(--accent-green)" }}>{expSt ?? "—"}</div>
                              </div>
                              <div className="diff-block">
                                <div className="diff-label">Actual Status</div>
                                <div className="sb-code" style={{ fontSize:22, marginTop:6, color:"var(--accent-rose)" }}>{actSt ?? "—"}</div>
                              </div>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* Failures without AI report */}
          {failsNoBug.length > 0 && (
            <>
              <div className="section-label" style={{ marginTop: 8 }}>⚠ Failures Without Bug Report</div>
              <div className="card">
                {failsNoBug.map(test => (
                  <div key={test.test_id} className="plain-fail-row">
                    <span className="rr-id">{test.test_id}</span>
                    <span className="rr-method" style={{ background:`${getMethodColor(test.method)}20`, color:getMethodColor(test.method), fontSize:11, fontWeight:700, padding:"2px 7px", borderRadius:4 }}>{test.method}</span>
                    <span style={{ color:"var(--text-secondary)", fontSize:13 }}>{test.endpoint}</span>
                    <span style={{ color:"var(--text-muted)", fontSize:12, marginLeft:"auto" }}>{test.failure_reason?.slice(0,60) || "No reason given"}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   PAGE: HISTORY
══════════════════════════════════════════════════════ */
function HistoryPage({ testRuns, onLoadRun }) {
  const maxTests = Math.max(...(testRuns.map(r => r.total_tests || 0)), 1);

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Run History</h2>
          <p className="page-sub">{testRuns.length} recorded test run{testRuns.length !== 1 ? "s" : ""}</p>
        </div>
      </div>

      {testRuns.length === 0 ? (
        <div className="empty-page">
          <div className="empty-icon">📂</div>
          <p>No history yet. Run your first test suite.</p>
        </div>
      ) : (
        <>
          {/* Trend chart */}
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="card-header">
              <span className="card-title">Pass/Fail Trend</span>
              <span style={{ fontSize:11, color:"var(--text-muted)" }}>Last {Math.min(testRuns.length, 10)} runs</span>
            </div>
            <div className="trend-chart">
              {testRuns.slice(-10).map((run, i) => {
                const passH = maxTests > 0 ? ((run.passed_tests||0)/maxTests)*100 : 0;
                const failH = maxTests > 0 ? ((run.failed_tests||0)/maxTests)*100 : 0;
                return (
                  <div key={run.id||i} className="trend-col" onClick={() => onLoadRun(run.id)}>
                    <div className="trend-bars">
                      {failH > 0 && <div className="trend-bar rose" style={{ height:`${failH}%` }}/>}
                      {passH > 0 && <div className="trend-bar green" style={{ height:`${passH}%` }}/>}
                    </div>
                    <div className="trend-label">#{run.id||i+1}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Runs table */}
          <div className="card">
            <div className="history-table">
              <div className="history-th-row">
                <span>Run ID</span>
                <span>Date & Time</span>
                <span>Total</span>
                <span>Passed</span>
                <span>Failed</span>
                <span>Pass Rate</span>
                <span></span>
              </div>
              {testRuns.map(run => {
                const rate = run.total_tests > 0 ? ((run.passed_tests/run.total_tests)*100).toFixed(1) : 0;
                return (
                  <div key={run.id} className="history-td-row" onClick={() => onLoadRun(run.id)}>
                    <span className="history-run-id">#{run.id}</span>
                    <span className="history-date">{run.created_at ? new Date(run.created_at).toLocaleString() : "—"}</span>
                    <span style={{ color:"var(--text-primary)", fontWeight:600 }}>{run.total_tests ?? "—"}</span>
                    <span style={{ color:"var(--accent-green)", fontWeight:600 }}>✓ {run.passed_tests ?? 0}</span>
                    <span style={{ color:"var(--accent-rose)", fontWeight:600 }}>✗ {run.failed_tests ?? 0}</span>
                    <span>
                      <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                        <div style={{ flex:1, background:"rgba(255,255,255,0.06)", borderRadius:99, height:5, overflow:"hidden" }}>
                          <div style={{ height:"100%", width:`${rate}%`, background:"linear-gradient(90deg,#10b981,#06b6d4)", borderRadius:99 }}/>
                        </div>
                        <span style={{ fontSize:12, color:"var(--text-secondary)", minWidth:38 }}>{rate}%</span>
                      </div>
                    </span>
                    <span><button className="shortcut-btn" style={{ fontSize:11 }}>Load →</button></span>
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

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:5000"
).replace(/\/+$/, "");

/* ══════════════════════════════════════════════════════
   ROOT APP
══════════════════════════════════════════════════════ */
export default function App() {
  const [page, setPage]           = useState("dashboard");
  const [testData, setTestData]   = useState(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState("");
  const [testRuns, setTestRuns]   = useState([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8000");
  const [openapiUrl, setOpenapiUrl] = useState(
    "http://127.0.0.1:8000/openapi.json"
  );


  const runTests = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const res = await fetch(`${API_BASE_URL}/run-tests`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          base_url: baseUrl.trim(),
          openapi_url: openapiUrl.trim(),
        }),
      });

      if (!res.ok) {
        const message = await res.text();
        throw new Error(message || "Test execution failed.");
      }

      const data = await res.json();
      setTestData(data.data);
      setPage("results");
    } catch (err) {
      setError(
        err.message || "Cannot reach backend. Ensure both servers are running."
      );
    } finally {
      setLoading(false);
    }
  }, [baseUrl, openapiUrl]);


  const loadHistory = useCallback(async () => {
    try {
      const res  = await fetch(`${API_BASE_URL}/test-runs`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTestRuns(data.data);
      setHistoryLoaded(true);
    } catch {
      setError("Cannot load history.");
    }
  }, []);

  const loadRunResults = useCallback(async (runId) => {
    try {
      const [resR, resB] = await Promise.all([
        fetch(`${API_BASE_URL}/test-runs/${runId}/results`),
        fetch(`${API_BASE_URL}/test-runs/${runId}/bugs`),
      ]);
      const [rData, bData] = await Promise.all([resR.json(), resB.json()]);
      const merged = rData.data.map(test => {
        const norm = {
          ...test,
          expected_status: test.expected_status ?? test.expected?.status_code ?? null,
          actual_status:   test.actual_status   ?? test.actual?.status_code   ?? null,
          expected_body:   test.expected_body   ?? test.expected?.body         ?? null,
          actual_body:     test.actual_body     ?? test.actual?.body           ?? null,
        };
        const bug = bData.data.find(b => b.test_id === test.test_id);
        if (!bug) return norm;
        return { ...norm, ai_analysis:{ summary:bug.summary, possible_cause:bug.possible_cause, severity:bug.severity, recommendation:bug.recommendation }, bug_report:bug };
      });
      const total = merged.length;
      const passed = merged.filter(t => t.status==="PASS").length;
      const failed = merged.filter(t => t.status==="FAIL").length;
      setTestData({ results:merged, total, passed, failed, pass_rate: total>0?((passed/total)*100).toFixed(2):0 });
      setPage("results");
    } catch {
      setError("Failed to load run results.");
    }
  }, []);

  // Auto-load history when switching to history tab
  useEffect(() => {
    if (page === "history" && !historyLoaded) loadHistory();
  }, [page, historyLoaded, loadHistory]);

  const navItems = [
    { id:"dashboard", icon:"⬡", label:"Dashboard" },
    { id:"results",   icon:"📋", label:"Test Results",
      badge: testData?.failed > 0 ? null : null },
    { id:"bugs",      icon:"🐛", label:"Bug Reports",
      badge: testData ? testData.results.filter(t=>t.status==="FAIL").length : null },
    { id:"history",   icon:"🕒", label:"Run History" },
  ];

  return (
    <div className="app">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-orb">🤖</div>
          <div>
            <div className="logo-name">AI Test Agent</div>
            <div className="logo-sub">API Quality Platform</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          <div className="nav-section-label">Navigation</div>
          {navItems.map(item => (
            <button
              key={item.id}
              className={`nav-btn ${page === item.id ? "active" : ""}`}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.badge > 0 && (
                <span className="nav-badge">{item.badge}</span>
              )}
            </button>
          ))}

          <div className="nav-section-label" style={{ marginTop: 12 }}>Actions</div>
          <button
            className={`nav-btn run-nav-btn ${loading ? "running" : ""}`}
            onClick={runTests}
            disabled={loading}
          >
            <span className="nav-icon">{loading ? "⟳" : "▶"}</span>
            <span>{loading ? "Running Tests…" : "Run Tests"}</span>
            {loading && <div className="spinner" style={{ width:12, height:12, marginLeft:"auto" }}/>}
          </button>
          <button className="nav-btn" onClick={loadHistory}>
            <span className="nav-icon">↻</span>
            <span>Refresh History</span>
          </button>
        </nav>

        <div className="sidebar-footer">
          <div className="server-status">
            <div className="ss-row"><div className="ss-dot online"/><span>Agent API :5000</span></div>
            <div className="ss-row"><div className="ss-dot online"/><span>Target API :8000</span></div>
          </div>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="main-content">
        {/* Topbar */}
        <div className="topbar">
          <div className="breadcrumb">
            <span style={{ color:"var(--text-muted)" }}>Platform</span>
            <span style={{ color:"var(--text-muted)" }}>›</span>
            <span style={{ color:"var(--text-primary)", fontWeight:600 }}>
              {navItems.find(n => n.id === page)?.label}
            </span>
          </div>
          <div style={{ display:"flex", gap:10, alignItems:"center" }}>
            {testData && (
              <div className="topbar-stat">
                <span style={{ color:"var(--accent-green)" }}>✓ {testData.passed}</span>
                <span style={{ color:"var(--text-muted)" }}>/</span>
                <span style={{ color:"var(--accent-rose)" }}>✗ {testData.failed}</span>
                <span style={{ color:"var(--text-muted)" }}>· {testData.total} total</span>
              </div>
            )}
            <button className="btn btn-primary" id="main-run-btn" onClick={runTests} disabled={loading}>
              {loading ? <><div className="spinner"/>Running…</> : <>▶ Run Tests</>}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="error-banner">
            ⚠ {error}
            <button className="icon-btn" style={{ marginLeft:"auto" }} onClick={() => setError("")}>✕</button>
          </div>
        )}

        {/* Pages */}
        {page === "dashboard" && (
        <DashboardPage
          testData={testData}
          onRunTests={runTests}
          loading={loading}
          onNavigate={setPage}
          baseUrl={baseUrl}
          setBaseUrl={setBaseUrl}
          openapiUrl={openapiUrl}            
          setOpenapiUrl={setOpenapiUrl}
          />
        )}
        {page === "results" && (
          <ResultsPage testData={testData}/>
        )}
        {page === "bugs" && (
          <BugsPage testData={testData}/>
        )}
        {page === "history" && (
          <HistoryPage testRuns={testRuns} onLoadRun={loadRunResults}/>
        )}
      </main>
    </div>
  );
}