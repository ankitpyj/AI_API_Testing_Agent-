import { ThemeToggle } from "./ThemeToggle.jsx";

const getInitials = (name = "") => {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 0 || !parts[0]) return "U";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

const PAGE_TITLES = {
  dashboard: "Overview",
  projects: "Projects",
  results: "Test Results",
  bugs: "Bug Reports",
  history: "Run History",
  analytics: "Analytics & Defect Telemetry",
  usage: "Usage & Plan",
  settings: "Settings",
  admin: "Admin Portal",
};

export function Topbar({
  page,
  selectedProject,
  onNavigate,
  currentUser,
  theme,
  onToggleTheme,
  onLogout,
  onRunTests,
  loading,
  testData,
  onOpenMobileNav,
}) {
  const currentTitle = PAGE_TITLES[page] || "Platform";

  return (
    <header className="topbar">
      {/* Left: Mobile Hamburger & Breadcrumb */}
      <div className="topbar-left">
        <button
          type="button"
          className="hamburger-btn"
          onClick={onOpenMobileNav}
          aria-label="Open navigation menu"
          title="Open navigation menu"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        <nav className="breadcrumb" aria-label="Breadcrumb">
          <span className="breadcrumb-root">Platform</span>
          <span className="breadcrumb-sep">›</span>
          <span className="breadcrumb-current">{currentTitle}</span>
        </nav>
      </div>

      {/* Right: Actions, Project context, Theme toggle, User profile */}
      <div className="topbar-right">
        {/* Test stats summary badge (if available) */}
        {testData && (
          <div className="topbar-stat hide-on-mobile" title="Latest execution summary">
            <span style={{ color: "var(--success)" }}>✓ {testData.passed}</span>
            <span style={{ color: "var(--text-muted)" }}>/</span>
            <span style={{ color: "var(--danger)" }}>✗ {testData.failed}</span>
            <span style={{ color: "var(--text-muted)" }}>· {testData.total} total</span>
          </div>
        )}

        {/* Active Project Pill */}
        {selectedProject && (
          <button
            type="button"
            className="topbar-project-pill"
            onClick={() => onNavigate("projects")}
            title={`Active Context: ${selectedProject.project_name} (${selectedProject.base_url}). Click to manage projects.`}
          >
            <span className="tpp-icon">📁</span>
            <span className="tpp-name">{selectedProject.project_name}</span>
            {selectedProject.auth_type && selectedProject.auth_type !== "none" && (
              <span className="tpp-auth">
                {selectedProject.auth_type === "bearer" ? "Bearer" : "API Key"}
              </span>
            )}
          </button>
        )}

        {/* Theme Switcher */}
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />

        {/* User Profile Badge */}
        {currentUser && (
          <div
            className="user-profile-badge hide-on-mobile"
            title={`Signed in as ${currentUser.email} (${currentUser.role || "user"})`}
          >
            <div className="user-avatar-circle">
              {getInitials(currentUser.full_name)}
            </div>
            <span className="user-display-name">{currentUser.full_name}</span>
          </div>
        )}

        {/* Sign Out (Desktop) */}
        <button
          type="button"
          className="btn btn-ghost btn-sm hide-on-mobile"
          onClick={onLogout}
          title="Sign out of your session"
        >
          Sign Out
        </button>

        {/* Primary Run Tests Action */}
        <button
          type="button"
          className="btn btn-primary btn-sm topbar-run-btn"
          onClick={onRunTests}
          disabled={loading}
        >
          {loading ? (
            <>
              <div className="spinner" style={{ width: 13, height: 13 }} />
              <span className="hide-on-mobile">Running…</span>
            </>
          ) : (
            <>
              <span style={{ fontSize: 11 }}>▶</span>
              <span>Run Tests</span>
            </>
          )}
        </button>
      </div>
    </header>
  );
}
