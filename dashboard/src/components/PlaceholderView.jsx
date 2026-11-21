import { ThemeToggle } from "./ThemeToggle.jsx";

export function PlaceholderView({
  type = "usage",
  currentUser,
  theme,
  onToggleTheme,
  onNavigate,
  selectedProject,
}) {
  if (type === "usage") {
    return (
      <div className="page fade-in" style={{ maxWidth: 1080, margin: "0 auto" }}>
        <div className="page-header" style={{ marginBottom: 24 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
                Usage & Subscription Plan
              </h1>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: 0.8,
                  padding: "3px 8px",
                  borderRadius: 4,
                  background: "var(--brand-surface)",
                  border: "1px solid var(--brand-border)",
                  color: "var(--brand-primary)",
                  textTransform: "uppercase",
                }}
              >
                Plan: {currentUser?.plan?.toUpperCase() || "INTERNAL DEMO"}
              </span>
            </div>
            <p className="page-sub">
              Monitor monthly test case executions, AI operation allowances, and tenant limits.
            </p>
          </div>
          <button
            className="btn btn-ghost"
            onClick={() => onNavigate("dashboard")}
            style={{ fontSize: 13 }}
          >
            ← Return to Dashboard
          </button>
        </div>

        {/* Demo Mode Notice */}
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
          <div style={{ fontSize: 28, flexShrink: 0 }}>🛡️</div>
          <div>
            <h3 style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>
              Platform Operating in Internal / Demo Mode
            </h3>
            <p style={{ margin: 0, fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
              Usage tracking and quota reservation mechanisms are fully active and telemetry-enabled.
              Hard monetization gating is disabled during this phase to support internal testing.
            </p>
          </div>
        </div>

        {/* Quota Telemetry Cards */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 18,
            marginBottom: 24,
          }}
        >
          <div className="card" style={{ padding: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>
                Test Case Quota
              </span>
              <span style={{ fontSize: 18 }}>🧪</span>
            </div>
            <div style={{ fontSize: 28, fontWeight: 800, color: "var(--text-primary)", marginBottom: 6 }}>
              {currentUser?.plan === "free" ? "200" : "Unlimited"}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              Monthly verified endpoint assertions
            </div>
            <div className="progress-bar-wrap" style={{ marginTop: 14 }}>
              <div className="progress-bar-fill" style={{ width: "35%", background: "var(--success)" }} />
            </div>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>
                AI Operations Quota
              </span>
              <span style={{ fontSize: 18 }}>🤖</span>
            </div>
            <div style={{ fontSize: 28, fontWeight: 800, color: "var(--brand-primary)", marginBottom: 6 }}>
              {currentUser?.plan === "free" ? "0 (Disabled)" : "500 ops"}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              Gemini AI test generation & root-cause analysis
            </div>
            <div className="progress-bar-wrap" style={{ marginTop: 14 }}>
              <div className="progress-bar-fill" style={{ width: "20%", background: "var(--brand-primary)" }} />
            </div>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>
                Workspace Projects
              </span>
              <span style={{ fontSize: 18 }}>📁</span>
            </div>
            <div style={{ fontSize: 28, fontWeight: 800, color: "var(--info)", marginBottom: 6 }}>
              Active
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              Isolated credentials, OpenAPI discovery & history
            </div>
            <div className="progress-bar-wrap" style={{ marginTop: 14 }}>
              <div className="progress-bar-fill" style={{ width: "100%", background: "var(--info)" }} />
            </div>
          </div>
        </div>

        {/* Plan Features Table */}
        <div className="card" style={{ padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
              Tier Capabilities & Monetization Roadmap
            </h3>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Upcoming Milestone: Task 9</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--border-subtle)", fontSize: 13 }}>
              <span style={{ color: "var(--text-secondary)" }}>AES-256-GCM API Credential Encryption</span>
              <span style={{ color: "var(--success)", fontWeight: 600 }}>✓ Active on all plans</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--border-subtle)", fontSize: 13 }}>
              <span style={{ color: "var(--text-secondary)" }}>SSRF, Private IP & DNS Rebinding Mitigation</span>
              <span style={{ color: "var(--success)", fontWeight: 600 }}>✓ Active on all plans</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--border-subtle)", fontSize: 13 }}>
              <span style={{ color: "var(--text-secondary)" }}>Automated OpenAPI Endpoint Discovery</span>
              <span style={{ color: "var(--success)", fontWeight: 600 }}>✓ Active on all plans</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", fontSize: 13 }}>
              <span style={{ color: "var(--text-secondary)" }}>Self-Serve Billing & Stripe Integration</span>
              <span style={{ color: "var(--brand-primary)", fontWeight: 600 }}>⏳ Scheduled for Task 9</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Settings View
  return (
    <div className="page fade-in" style={{ maxWidth: 880, margin: "0 auto" }}>
      <div className="page-header" style={{ marginBottom: 24 }}>
        <div>
          <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
            Workspace Settings
          </h1>
          <p className="page-sub">
            Manage your interface appearance, security defaults, and account profile.
          </p>
        </div>
        <button
          className="btn btn-ghost"
          onClick={() => onNavigate("dashboard")}
          style={{ fontSize: 13 }}
        >
          ← Return to Dashboard
        </button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {/* Appearance Settings */}
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
            Theme & Appearance
          </h3>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--text-secondary)" }}>
            Select your preferred visual style. Preferences are persisted in your local browser storage.
          </p>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "14px 18px",
              background: "var(--bg-subtle)",
              borderRadius: "var(--r-sm)",
              border: "1px solid var(--border-default)",
            }}
          >
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text-primary)" }}>
                Active Theme: <span style={{ textTransform: "capitalize", color: "var(--brand-primary)" }}>{theme}</span>
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                Switch between high-contrast Dark Mode and clean Slate Light Mode
              </div>
            </div>
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          </div>
        </div>

        {/* Account Identity */}
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
            Account Profile
          </h3>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--text-secondary)" }}>
            Your authenticated session identity and tenant scope.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-default)" }}>
              <span style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
                Full Name
              </span>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", marginTop: 4 }}>
                {currentUser?.full_name || "—"}
              </div>
            </div>

            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-default)" }}>
              <span style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
                Email Address
              </span>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", marginTop: 4, fontFamily: "var(--mono)" }}>
                {currentUser?.email || "—"}
              </div>
            </div>

            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-default)" }}>
              <span style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
                System Role
              </span>
              <div style={{ fontSize: 14, fontWeight: 600, color: currentUser?.role === "admin" ? "var(--brand-primary)" : "var(--text-primary)", marginTop: 4 }}>
                {currentUser?.role === "admin" ? "🛡️ Platform Administrator" : "Standard User"}
              </div>
            </div>

            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-default)" }}>
              <span style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
                Active Project
              </span>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--info)", marginTop: 4 }}>
                {selectedProject?.project_name || "None (Default API)"}
              </div>
            </div>
          </div>
        </div>

        {/* Security Summary */}
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
            Security & Compliance
          </h3>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--text-secondary)" }}>
            Platform cryptographic protection and session security.
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "var(--text-secondary)" }}>
              <span style={{ color: "var(--success)" }}>🔒</span>
              <span><strong>AES-256-GCM</strong> authenticated encryption active for all project API secrets.</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "var(--text-secondary)" }}>
              <span style={{ color: "var(--success)" }}>🛡️</span>
              <span><strong>Tenant Isolation</strong> enforced at database query level via strict user ownership checks.</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "var(--text-secondary)" }}>
              <span style={{ color: "var(--success)" }}>🌐</span>
              <span><strong>SSRF Filter</strong> active: Blocks 169.254.169.254, internal RFC-1918 ranges, and re-resolves DNS on every redirect.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
