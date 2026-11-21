const getInitials = (name = "") => {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 0 || !parts[0]) return "U";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

export function Sidebar({
  page,
  onNavigate,
  currentUser,
  onLogout,
  testData,
  selectedProject,
  loading,
  onRunTests,
  onRefreshHistory,
  mobileOpen,
  onCloseMobile,
}) {
  const bugCount = testData ? testData.results.filter((t) => t.status === "FAIL").length : 0;

  const navItems = [
    {
      id: "dashboard",
      label: "Overview",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
        </svg>
      ),
    },
    {
      id: "projects",
      label: "Projects",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        </svg>
      ),
    },
    {
      id: "results",
      label: "Test Results",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
          <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
          <polyline points="9 14 11 16 15 11" />
        </svg>
      ),
    },
    {
      id: "bugs",
      label: "Bug Reports",
      badge: bugCount > 0 ? bugCount : null,
      badgeColor: "rose",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="6" y="8" width="12" height="10" rx="4" />
          <path d="m19 7-3 2" />
          <path d="m5 7 3 2" />
          <path d="m19 19-3-2" />
          <path d="m5 19 3-2" />
          <path d="M20 13h-2" />
          <path d="M4 13h2" />
          <path d="M10 4 9 6" />
          <path d="M14 4l1 2" />
        </svg>
      ),
    },
    {
      id: "history",
      label: "Run History",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      ),
    },
    {
      id: "analytics",
      label: "Analytics",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
      ),
    },
    {
      id: "usage",
      label: "Usage & Plan",
      badge: currentUser?.plan === "free" ? "Free" : "Demo",
      badgeColor: "brand",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
          <line x1="1" y1="10" x2="23" y2="10" />
        </svg>
      ),
    },
    {
      id: "settings",
      label: "Settings",
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      ),
    },
    ...(currentUser?.role === "admin"
      ? [
          {
            id: "admin",
            label: "Admin Portal",
            badge: "Admin",
            badgeColor: "violet",
            icon: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
            ),
          },
        ]
      : []),
  ];

  const handleNavClick = (id) => {
    onNavigate(id);
    if (onCloseMobile) onCloseMobile();
  };

  return (
    <>
      {/* Mobile Drawer Backdrop */}
      {mobileOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}

      <aside className={`sidebar ${mobileOpen ? "sidebar-mobile-open" : ""}`}>
        {/* Brand Header */}
        <div className="sidebar-logo">
          <div className="logo-orb">🤖</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="logo-name">AI Test Agent</div>
            <div className="logo-sub">SaaS Quality Platform</div>
          </div>
          {/* Mobile close button */}
          <button
            type="button"
            className="sidebar-mobile-close"
            onClick={onCloseMobile}
            aria-label="Close navigation"
          >
            ✕
          </button>
        </div>

        {/* Active Project Workspace Pill in Sidebar */}
        <div className="sidebar-workspace-box">
          <div className="sw-label">Active Workspace</div>
          <button
            type="button"
            className="sw-button"
            onClick={() => handleNavClick("projects")}
            title="Click to view or switch projects"
          >
            <span className="sw-icon">📁</span>
            <div className="sw-info">
              <span className="sw-name">
                {selectedProject ? selectedProject.project_name : "Default Workspace"}
              </span>
              <span className="sw-mode">
                {selectedProject
                  ? selectedProject.auth_type === "bearer"
                    ? "Bearer Auth"
                    : selectedProject.auth_type === "api_key"
                    ? "API Key Auth"
                    : "Public API"
                  : "No Auth Bound"}
              </span>
            </div>
            <span className="sw-chevron">›</span>
          </button>
        </div>

        {/* Main Navigation */}
        <nav className="sidebar-nav">
          <div className="nav-section-label">Core Platform</div>
          {navItems.slice(0, 6).map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-btn ${page === item.id ? "active" : ""}`}
              onClick={() => handleNavClick(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
              {item.badge && (
                <span className={`nav-badge ${item.badgeColor || "default"}`}>
                  {item.badge}
                </span>
              )}
            </button>
          ))}

          <div className="nav-section-label" style={{ marginTop: 12 }}>
            Management
          </div>
          {navItems.slice(6).map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-btn ${page === item.id ? "active" : ""}`}
              onClick={() => handleNavClick(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
              {item.badge && (
                <span className={`nav-badge ${item.badgeColor || "default"}`}>
                  {item.badge}
                </span>
              )}
            </button>
          ))}

          {/* Quick Actions */}
          <div className="nav-section-label" style={{ marginTop: 12 }}>
            Actions
          </div>
          <button
            type="button"
            className={`nav-btn run-nav-btn ${loading ? "running" : ""}`}
            onClick={onRunTests}
            disabled={loading}
          >
            <span className="nav-icon">
              {loading ? (
                <div className="spinner" style={{ width: 14, height: 14 }} />
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
              )}
            </span>
            <span>{loading ? "Running Suite…" : "Run Test Suite"}</span>
          </button>

          <button
            type="button"
            className="nav-btn"
            onClick={onRefreshHistory}
            style={{ fontSize: 12.5 }}
          >
            <span className="nav-icon">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
            </span>
            <span>Refresh Telemetry</span>
          </button>
        </nav>

        {/* User Profile & Sign Out Footer */}
        <div className="sidebar-user-section">
          <div className="sidebar-user-info">
            <div className="user-avatar-circle">
              {getInitials(currentUser?.full_name)}
            </div>
            <div className="sidebar-user-text">
              <span className="sidebar-user-name" title={currentUser?.full_name}>
                {currentUser?.full_name || "User"}
              </span>
              <span className="sidebar-user-email" title={currentUser?.email}>
                {currentUser?.email || ""}
              </span>
            </div>
            <button
              type="button"
              className="logout-icon-btn"
              onClick={onLogout}
              title="Sign out of account"
              aria-label="Sign out of account"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>

          <div className="sidebar-footer-status">
            <div className="server-status">
              <div className="ss-row">
                <div className="ss-dot online" />
                <span>Agent API :5000</span>
              </div>
              <div className="ss-row">
                <div className="ss-dot online" />
                <span>Target API :8000</span>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
