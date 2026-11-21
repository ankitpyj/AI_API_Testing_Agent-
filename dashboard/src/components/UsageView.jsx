import { useState, useEffect } from "react";

// Canonical plan definitions matching agent_backend/plans.py
const PLAN_TIERS = {
  internal_demo: {
    key: "internal_demo",
    name: "Internal / Demo",
    badgeColor: "brand",
    description: "Internal testing & demo tier with generous development capacity and full AI capabilities.",
    max_projects: 100,
    monthly_test_runs: 10000,
    monthly_test_cases: 100000,
    monthly_ai_operations: 5000,
    features: [
      { name: "Automated OpenAPI Discovery", enabled: true },
      { name: "Rule-Based Test Generation", enabled: true },
      { name: "AI Test Generation (Gemini)", enabled: true },
      { name: "AI Failure Analysis & Bugs", enabled: true },
      { name: "SaaS Analytics & Trends", enabled: true },
      { name: "AES-256-GCM Credential Vault", enabled: true },
      { name: "SSRF & DNS Rebinding Protection", enabled: true },
    ],
  },
  free: {
    key: "free",
    name: "Free Tier",
    badgeColor: "gray",
    description: "Starter plan for developers testing individual endpoints and basic schemas.",
    max_projects: 3,
    monthly_test_runs: 50,
    monthly_test_cases: 500,
    monthly_ai_operations: 0,
    features: [
      { name: "Automated OpenAPI Discovery", enabled: true },
      { name: "Rule-Based Test Generation", enabled: true },
      { name: "AI Test Generation (Gemini)", enabled: false, note: "Requires Pro plan" },
      { name: "AI Failure Analysis & Bugs", enabled: false, note: "Requires Pro plan" },
      { name: "SaaS Analytics & Trends", enabled: true },
      { name: "AES-256-GCM Credential Vault", enabled: true },
      { name: "SSRF & DNS Rebinding Protection", enabled: true },
    ],
  },
  pro: {
    key: "pro",
    name: "Pro Developer",
    badgeColor: "cyan",
    description: "Expanded capacity for agile engineering teams running CI/CD pipelines.",
    max_projects: 20,
    monthly_test_runs: 500,
    monthly_test_cases: 10000,
    monthly_ai_operations: 500,
    features: [
      { name: "Automated OpenAPI Discovery", enabled: true },
      { name: "Rule-Based Test Generation", enabled: true },
      { name: "AI Test Generation (Gemini)", enabled: true },
      { name: "AI Failure Analysis & Bugs", enabled: true },
      { name: "SaaS Analytics & Trends", enabled: true },
      { name: "AES-256-GCM Credential Vault", enabled: true },
      { name: "SSRF & DNS Rebinding Protection", enabled: true },
    ],
  },
  business: {
    key: "business",
    name: "Business / Enterprise",
    badgeColor: "violet",
    description: "High-throughput automated testing for large engineering organizations.",
    max_projects: 100,
    monthly_test_runs: 2500,
    monthly_test_cases: 50000,
    monthly_ai_operations: 2500,
    features: [
      { name: "Automated OpenAPI Discovery", enabled: true },
      { name: "Rule-Based Test Generation", enabled: true },
      { name: "AI Test Generation (Gemini)", enabled: true },
      { name: "AI Failure Analysis & Bugs", enabled: true },
      { name: "SaaS Analytics & Trends", enabled: true },
      { name: "AES-256-GCM Credential Vault", enabled: true },
      { name: "SSRF & DNS Rebinding Protection", enabled: true },
    ],
  },
};

export function UsageView({ apiBaseUrl, token, currentUser, onNavigate }) {
  const [usageData, setUsageData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const userPlanKey = (currentUser?.plan || "internal_demo").toLowerCase();
  const currentPlan = PLAN_TIERS[userPlanKey] || PLAN_TIERS.internal_demo;

  // Load authoritative usage metrics for the tenant matching quota enforcement
  useEffect(() => {
    if (!token) return;
    let ignore = false;

    const fetchUsage = async () => {
      try {
        const headers = { Authorization: `Bearer ${token}` };
        const res = await fetch(`${apiBaseUrl}/auth/usage`, { headers });
        if (res.ok) {
          const json = await res.json();
          if (!ignore) {
            setUsageData(json.data);
            setLoading(false);
          }
        } else {
          // Fallback to overview if /auth/usage unavailable
          const fbRes = await fetch(`${apiBaseUrl}/analytics/overview`, { headers });
          if (fbRes.ok) {
            const fbJson = await fbRes.json();
            if (!ignore) {
              setUsageData({
                metrics: {
                  total_projects: fbJson.total_projects || 0,
                  monthly_test_runs: fbJson.total_test_runs || 0,
                  monthly_test_cases: fbJson.total_test_cases || 0,
                  monthly_ai_operations: fbJson.total_bug_reports || 0,
                  isEstimatedAi: true,
                },
                limits: {
                  max_projects: currentPlan.max_projects,
                  monthly_test_runs: currentPlan.monthly_test_runs,
                  monthly_test_cases: currentPlan.monthly_test_cases,
                  monthly_ai_operations: currentPlan.monthly_ai_operations,
                },
              });
              setLoading(false);
            }
          } else {
            throw new Error("Failed to load quota metrics.");
          }
        }
      } catch (err) {
        if (!ignore) {
          setError(err.message || "Failed to load usage counters.");
          setLoading(false);
        }
      }
    };

    fetchUsage();

    return () => {
      ignore = true;
    };
  }, [apiBaseUrl, token, currentPlan]);

  // Derived real usage metrics from authoritative backend response
  const metrics = usageData?.metrics || {};
  const limits = usageData?.limits || currentPlan;

  const activeProjectsCount = metrics.total_projects ?? 0;
  const monthlyRunsCount = metrics.monthly_test_runs ?? 0;
  const monthlyCasesCount = metrics.monthly_test_cases ?? 0;
  const monthlyAiOpsCount = metrics.monthly_ai_operations ?? 0;
  const isEstimatedAi = Boolean(metrics.isEstimatedAi);

  // Quota calculators
  const quotas = [
    {
      id: "projects",
      title: "Active Projects",
      used: activeProjectsCount,
      limit: limits.max_projects ?? currentPlan.max_projects,
      unit: "Projects",
      description: "Projects registered under your tenant scope",
    },
    {
      id: "runs",
      title: "Monthly Test Runs",
      used: monthlyRunsCount,
      limit: limits.monthly_test_runs ?? currentPlan.monthly_test_runs,
      unit: "Runs / Mo",
      description: "Automated test suites executed in current UTC calendar month",
    },
    {
      id: "cases",
      title: "Monthly Test Cases",
      used: monthlyCasesCount,
      limit: limits.monthly_test_cases ?? currentPlan.monthly_test_cases,
      unit: "Tests / Mo",
      description: "Individual endpoint assertions executed in current UTC calendar month",
    },
    {
      id: "ai_ops",
      title: "Monthly AI Operations",
      used: monthlyAiOpsCount,
      limit: limits.monthly_ai_operations ?? currentPlan.monthly_ai_operations,
      unit: "AI Ops / Mo",
      description: isEstimatedAi
        ? "Estimated from bug reports (Actual log unavailable)"
        : "Actual Gemini API operations logged this calendar month (UTC)",
      disabled: (limits.monthly_ai_operations ?? currentPlan.monthly_ai_operations) === 0,
      isEstimated: isEstimatedAi,
    },
  ];

  return (
    <div className="page fade-in" style={{ maxWidth: 1040, margin: "0 auto", paddingBottom: 60 }}>
      {/* ── Page Header ── */}
      <div className="page-header" style={{ marginBottom: 24 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
              Usage & Subscription Plan
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
              Plan: {currentPlan.name}
            </span>
          </div>
          <p className="page-sub">
            Authoritative monthly quota consumption aligned with backend UTC calendar-month enforcement
          </p>
        </div>

        <button
          className="btn btn-ghost"
          onClick={() => onNavigate && onNavigate("dashboard")}
          style={{ fontSize: 13 }}
        >
          ← Return to Dashboard
        </button>
      </div>

      {/* ── Operational Notice Banner ── */}
      <div
        className="card"
        style={{
          marginBottom: 24,
          padding: "16px 20px",
          background: "linear-gradient(135deg, var(--brand-surface) 0%, var(--bg-surface) 100%)",
          border: "1px solid var(--brand-border)",
          display: "flex",
          alignItems: "center",
          gap: 14,
        }}
      >
        <span style={{ fontSize: 26 }}>⚡</span>
        <div style={{ flex: 1 }}>
          <strong style={{ fontSize: 13.5, color: "var(--text-primary)" }}>
            Internal / Demo Mode Active
          </strong>
          <p style={{ margin: "2px 0 0", fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
            Your account is running under platform development mode. Hard quota enforcement is off by default, granting generous execution capacity and AI testing tools without requiring payment or billing checkout.
          </p>
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
          }}
        >
          ⚠️ {error}
        </div>
      )}

      {/* ── Loading State ── */}
      {loading && !usageData && (
        <div
          className="card"
          style={{
            padding: "40px 20px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontSize: 13,
            marginBottom: 28,
          }}
        >
          Loading authoritative quota metrics...
        </div>
      )}

      {/* ── Quota Usage Meters Grid ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
          gap: 16,
          marginBottom: 28,
        }}
      >
        {quotas.map((q) => {
          const limit = q.limit;
          const used = q.used;
          const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
          const remaining = limit > 0 ? Math.max(0, limit - used) : "Unlimited";
          const statusColor =
            q.disabled
              ? "var(--text-muted)"
              : pct >= 90
              ? "var(--danger)"
              : pct >= 70
              ? "var(--warning)"
              : "var(--success)";

          return (
            <div key={q.id} className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>
                  {q.title}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: "2px 6px",
                    borderRadius: "var(--r-xs)",
                    background: q.disabled ? "var(--bg-subtle)" : pct >= 90 ? "var(--danger-surface)" : "var(--success-surface)",
                    color: statusColor,
                    border: `1px solid ${q.disabled ? "var(--border-subtle)" : pct >= 90 ? "var(--danger-border)" : "var(--success-border)"}`,
                  }}
                >
                  {q.disabled ? "Disabled" : pct >= 90 ? "Near Limit" : "Healthy"}
                </span>
              </div>

              {/* Counter values */}
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 4 }}>
                <span style={{ fontSize: 26, fontWeight: 800, color: "var(--text-primary)", fontFamily: "var(--mono)" }}>
                  {used.toLocaleString()}
                </span>
                <span style={{ fontSize: 13, color: "var(--text-muted)", fontFamily: "var(--mono)" }}>
                  / {limit > 0 ? limit.toLocaleString() : "∞"} {q.unit}
                </span>
              </div>

              {/* Progress bar */}
              <div
                style={{
                  height: 6,
                  width: "100%",
                  background: "var(--bg-subtle)",
                  borderRadius: 3,
                  overflow: "hidden",
                  marginTop: 4,
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: q.disabled ? "0%" : `${pct}%`,
                    background: statusColor,
                    borderRadius: 3,
                    transition: "width 0.4s ease",
                  }}
                />
              </div>

              {/* Remaining / Description */}
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--text-secondary)", marginTop: 2 }}>
                <span>
                  {q.disabled ? "Unavailable on this plan" : `Remaining: ${typeof remaining === "number" ? remaining.toLocaleString() : remaining}`}
                </span>
                <span style={{ fontFamily: "var(--mono)" }}>{pct}%</span>
              </div>

              {/* Granular Source Tag */}
              {q.id === "ai_ops" && !q.disabled && (
                <div style={{ fontSize: 10.5, marginTop: 4 }}>
                  {q.isEstimated ? (
                    <span style={{ color: "var(--warning)", fontWeight: 600 }}>~ Estimated from Bug Reports</span>
                  ) : (
                    <span style={{ color: "var(--success)", fontWeight: 600 }}>✓ Authoritative Log (ai_usage_logs)</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Feature Entitlements Checklist ── */}
      <div className="card" style={{ padding: 24, marginBottom: 28 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
              Feature Entitlements & Platform Security
            </h3>
            <p style={{ margin: 0, fontSize: 12.5, color: "var(--text-muted)" }}>
              Capabilities granted under the <strong>{currentPlan.name}</strong> tier
            </p>
          </div>
          <span style={{ fontSize: 11, color: "var(--brand-primary)", fontWeight: 600 }}>
            Active Tenant #{currentUser?.id || "—"}
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
          {currentPlan.features.map((feat) => (
            <div
              key={feat.name}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                background: "var(--bg-subtle)",
                borderRadius: "var(--r-sm)",
                border: "1px solid var(--border-subtle)",
                fontSize: 12.5,
              }}
            >
              <span style={{ color: feat.enabled ? "var(--text-primary)" : "var(--text-muted)" }}>
                {feat.name}
              </span>
              <span
                style={{
                  fontWeight: 600,
                  fontSize: 11,
                  color: feat.enabled ? "var(--success)" : "var(--text-muted)",
                }}
              >
                {feat.enabled ? "✓ Enabled" : feat.note || "✗ Disabled"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Tier Comparison & Monetization Readiness ── */}
      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
          Monetization-Ready Tier Specifications
        </h3>
        <p style={{ margin: "0 0 16px", fontSize: 12.5, color: "var(--text-muted)" }}>
          Official platform tiers defined in <code style={{ fontFamily: "var(--mono)", fontSize: 11 }}>plans.py</code>. Quotas enforce monthly UTC calendar boundaries.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
          {Object.values(PLAN_TIERS).map((plan) => {
            const isCurrent = plan.key === userPlanKey;
            return (
              <div
                key={plan.key}
                style={{
                  padding: 18,
                  borderRadius: "var(--r-sm)",
                  background: isCurrent ? "var(--brand-surface)" : "var(--bg-subtle)",
                  border: `1px solid ${isCurrent ? "var(--brand-border)" : "var(--border-subtle)"}`,
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <strong style={{ fontSize: 14, color: isCurrent ? "var(--brand-primary)" : "var(--text-primary)" }}>
                    {plan.name}
                  </strong>
                  {isCurrent && (
                    <span
                      style={{
                        fontSize: 9.5,
                        fontWeight: 700,
                        padding: "2px 6px",
                        borderRadius: "var(--r-xs)",
                        background: "var(--brand-primary)",
                        color: "#ffffff",
                        textTransform: "uppercase",
                      }}
                    >
                      Active
                    </span>
                  )}
                </div>

                <p style={{ fontSize: 11.5, color: "var(--text-secondary)", margin: 0, lineHeight: 1.4, minHeight: 32 }}>
                  {plan.description}
                </p>

                <div style={{ fontSize: 11.5, color: "var(--text-muted)", display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                  <div>• Projects: <strong>{plan.max_projects}</strong></div>
                  <div>• Test Runs: <strong>{plan.monthly_test_runs.toLocaleString()} / mo</strong></div>
                  <div>• Test Cases: <strong>{plan.monthly_test_cases.toLocaleString()} / mo</strong></div>
                  <div>• AI Ops: <strong>{plan.monthly_ai_operations.toLocaleString()} / mo</strong></div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
