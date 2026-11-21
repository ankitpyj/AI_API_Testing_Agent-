import { ThemeToggle } from "./ThemeToggle.jsx";

export function SettingsView({
  currentUser,
  theme,
  onToggleTheme,
  onNavigate,
  onLogout,
}) {
  return (
    <div className="page fade-in" style={{ maxWidth: 900, margin: "0 auto", paddingBottom: 60 }}>
      {/* ── Page Header ── */}
      <div className="page-header" style={{ marginBottom: 24 }}>
        <div>
          <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
            Workspace & Account Settings
          </h1>
          <p className="page-sub">
            Manage your visual appearance, account identity, and review platform security defaults
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

      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {/* ── Section 1: Appearance & Theme ── */}
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 15.5, fontWeight: 700, color: "var(--text-primary)" }}>
            Theme & Appearance
          </h3>
          <p style={{ margin: "0 0 16px", fontSize: 12.5, color: "var(--text-secondary)" }}>
            Choose between dark mode and slate light mode. Your preference is automatically persisted to local browser storage.
          </p>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "16px 20px",
              background: "var(--bg-subtle)",
              borderRadius: "var(--r-sm)",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text-primary)" }}>
                Active Theme:{" "}
                <span style={{ textTransform: "capitalize", color: "var(--brand-primary)", fontWeight: 700 }}>
                  {theme} Mode
                </span>
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 3 }}>
                Switch between developer dark theme and clean slate light theme
              </div>
            </div>

            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          </div>
        </div>

        {/* ── Section 2: Account Profile & Tenant Scope ── */}
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 15.5, fontWeight: 700, color: "var(--text-primary)" }}>
            Account Profile & Tenant Scope
          </h3>
          <p style={{ margin: "0 0 16px", fontSize: 12.5, color: "var(--text-secondary)" }}>
            Your authenticated identity and multi-tenant security boundary
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14 }}>
            {/* Full Name */}
            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-subtle)" }}>
              <span style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.5 }}>
                Full Name
              </span>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", marginTop: 4 }}>
                {currentUser?.full_name || "—"}
              </div>
            </div>

            {/* Email Address */}
            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-subtle)" }}>
              <span style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.5 }}>
                Email Address
              </span>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", marginTop: 4, fontFamily: "var(--mono)" }}>
                {currentUser?.email || "—"}
              </div>
            </div>

            {/* Tenant ID */}
            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-subtle)" }}>
              <span style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.5 }}>
                Tenant Scope ID
              </span>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--brand-primary)", marginTop: 4, fontFamily: "var(--mono)" }}>
                User #{currentUser?.id || "—"}
              </div>
            </div>

            {/* Account Role */}
            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-subtle)" }}>
              <span style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.5 }}>
                Account Role
              </span>
              <div style={{ fontSize: 14, fontWeight: 700, color: currentUser?.role === "admin" ? "var(--brand-primary)" : "var(--text-primary)", marginTop: 4, textTransform: "uppercase" }}>
                {currentUser?.role || "USER"}
              </div>
            </div>

            {/* Assigned Plan */}
            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-subtle)" }}>
              <span style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.5 }}>
                Assigned Plan
              </span>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", marginTop: 4 }}>
                {currentUser?.plan ? currentUser.plan.toUpperCase() : "INTERNAL DEMO"}
              </div>
            </div>

            {/* Member Since */}
            <div style={{ background: "var(--bg-subtle)", padding: 14, borderRadius: "var(--r-sm)", border: "1px solid var(--border-subtle)" }}>
              <span style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.5 }}>
                Member Since
              </span>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text-primary)", marginTop: 4 }}>
                {currentUser?.created_at ? new Date(currentUser.created_at).toLocaleDateString() : "Active"}
              </div>
            </div>
          </div>
        </div>

        {/* ── Section 3: Platform Security & Privacy Controls ── */}
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 15.5, fontWeight: 700, color: "var(--text-primary)" }}>
            Security & Cryptographic Standards
          </h3>
          <p style={{ margin: "0 0 16px", fontSize: 12.5, color: "var(--text-secondary)" }}>
            Security guarantees verified across the backend engine and database layers
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "10px 14px",
                background: "var(--bg-subtle)",
                borderRadius: "var(--r-xs)",
                border: "1px solid var(--border-subtle)",
                fontSize: 12.5,
              }}
            >
              <div>
                <strong style={{ color: "var(--text-primary)" }}>AES-256-GCM Credential Encryption</strong>
                <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
                  Project API keys and Bearer tokens are encrypted with GCM authenticated encryption before database storage.
                </p>
              </div>
              <span style={{ color: "var(--success)", fontWeight: 700, fontSize: 11.5 }}>
                ✓ Enforced
              </span>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "10px 14px",
                background: "var(--bg-subtle)",
                borderRadius: "var(--r-xs)",
                border: "1px solid var(--border-subtle)",
                fontSize: 12.5,
              }}
            >
              <div>
                <strong style={{ color: "var(--text-primary)" }}>SSRF & Private Subnet Blocking</strong>
                <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
                  Real-time blocking of RFC 1918 subnets (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.1, link-local).
                </p>
              </div>
              <span style={{ color: "var(--success)", fontWeight: 700, fontSize: 11.5 }}>
                ✓ Enforced
              </span>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "10px 14px",
                background: "var(--bg-subtle)",
                borderRadius: "var(--r-xs)",
                border: "1px solid var(--border-subtle)",
                fontSize: 12.5,
              }}
            >
              <div>
                <strong style={{ color: "var(--text-primary)" }}>Authentication & Password Protection</strong>
                <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
                  Stateless HS256 JWT tokens with server-side bcrypt salted password hashing (12 rounds).
                </p>
              </div>
              <span style={{ color: "var(--success)", fontWeight: 700, fontSize: 11.5 }}>
                ✓ Enforced
              </span>
            </div>
          </div>
        </div>

        {/* ── Section 4: Session Actions ── */}
        <div className="card" style={{ padding: 24, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
          <div>
            <h3 style={{ margin: "0 0 4px", fontSize: 15.5, fontWeight: 700, color: "var(--text-primary)" }}>
              Session Management
            </h3>
            <p style={{ margin: 0, fontSize: 12.5, color: "var(--text-muted)" }}>
              Log out of your current session and securely clear stored access tokens from your browser.
            </p>
          </div>

          <button
            className="btn btn-ghost"
            style={{
              borderColor: "var(--danger-border)",
              color: "var(--danger)",
              fontSize: 13,
              padding: "8px 18px",
            }}
            onClick={() => onLogout && onLogout()}
          >
            Sign Out of Account
          </button>
        </div>
      </div>
    </div>
  );
}
