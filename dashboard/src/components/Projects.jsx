import { useState, useEffect, useMemo, useCallback } from "react";
import { EndpointExplorer } from "./EndpointExplorer.jsx";

export function ProjectsPage({
  apiBaseUrl,
  token,
  selectedProject,
  onSelectProject,
  onRunTestsWithProject,
}) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Search and Sort state
  const [searchTerm, setSearchTerm] = useState("");
  const [sortBy, setSortBy] = useState("newest"); // "newest" | "oldest" | "name"

  // Modal / Form state
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState("create"); // "create" | "edit"
  const [editId, setEditId] = useState(null);

  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8000");
  const [openapiUrl, setOpenapiUrl] = useState("http://127.0.0.1:8000/openapi.json");

  // Auth fields
  const [authType, setAuthType] = useState("none"); // "none" | "bearer" | "api_key"
  const [authHeaderName, setAuthHeaderName] = useState("X-API-KEY");
  const [authSecret, setAuthSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [existingHasCredentials, setExistingHasCredentials] = useState(false);
  const [clearCredentials, setClearCredentials] = useState(false);

  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState("");

  // Endpoint discovery modal
  const [discoveryModalOpen, setDiscoveryModalOpen] = useState(false);
  const [discoveredData, setDiscoveredData] = useState(null);

  // Delete confirmation
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);

  const fetchProjects = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${apiBaseUrl}/projects`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to load projects.");
      const json = await res.json();
      setProjects(json.data || []);
    } catch (err) {
      setError(err.message || "Cannot load projects. Ensure backend is running.");
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, token]);

  useEffect(() => {
    if (!token) return;
    let ignore = false;

    fetch(`${apiBaseUrl}/projects`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("Failed to load projects."))))
      .then((json) => {
        if (!ignore) {
          setProjects(json.data || []);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!ignore) {
          setError(err.message || "Cannot load projects. Ensure backend is running.");
          setLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [apiBaseUrl, token]);

  // Filtered and Sorted Projects
  const filteredAndSortedProjects = useMemo(() => {
    let result = [...projects];

    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase().trim();
      result = result.filter(
        (p) =>
          p.project_name.toLowerCase().includes(term) ||
          p.base_url.toLowerCase().includes(term) ||
          (p.description && p.description.toLowerCase().includes(term)) ||
          p.auth_type.toLowerCase().includes(term)
      );
    }

    if (sortBy === "newest") {
      result.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    } else if (sortBy === "oldest") {
      result.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    } else if (sortBy === "name") {
      result.sort((a, b) => a.project_name.localeCompare(b.project_name));
    }

    return result;
  }, [projects, searchTerm, sortBy]);

  const openCreateModal = () => {
    setModalMode("create");
    setEditId(null);
    setProjectName("");
    setDescription("");
    setBaseUrl("http://127.0.0.1:8000");
    setOpenapiUrl("http://127.0.0.1:8000/openapi.json");
    setAuthType("none");
    setAuthHeaderName("X-API-KEY");
    setAuthSecret("");
    setShowSecret(false);
    setExistingHasCredentials(false);
    setClearCredentials(false);
    setFormError("");
    setModalOpen(true);
  };

  const openEditModal = (proj) => {
    setModalMode("edit");
    setEditId(proj.id);
    setProjectName(proj.project_name);
    setDescription(proj.description || "");
    setBaseUrl(proj.base_url);
    setOpenapiUrl(proj.openapi_url || "");
    setAuthType(proj.auth_type || "none");
    setAuthHeaderName(proj.auth_header_name || "X-API-KEY");
    setAuthSecret("");
    setShowSecret(false);
    setExistingHasCredentials(Boolean(proj.has_credentials));
    setClearCredentials(false);
    setFormError("");
    setModalOpen(true);
  };

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    setFormError("");

    if (!projectName.trim()) {
      setFormError("Project name is required.");
      return;
    }
    if (!baseUrl.trim()) {
      setFormError("Base API URL is required.");
      return;
    }

    if (authType === "bearer" && modalMode === "create" && !authSecret.trim()) {
      setFormError("Bearer token is required for Bearer authentication.");
      return;
    }

    if (authType === "api_key") {
      if (!authHeaderName.trim()) {
        setFormError("Header name is required for API Key authentication.");
        return;
      }
      if (modalMode === "create" && !authSecret.trim()) {
        setFormError("API Key value is required for API Key authentication.");
        return;
      }
    }

    setFormLoading(true);
    try {
      const method = modalMode === "create" ? "POST" : "PUT";
      const endpoint =
        modalMode === "create"
          ? `${apiBaseUrl}/projects`
          : `${apiBaseUrl}/projects/${editId}`;

      const payload = {
        project_name: projectName.trim(),
        description: description.trim() || null,
        base_url: baseUrl.trim(),
        openapi_url: openapiUrl.trim() || null,
        auth_type: authType,
        auth_header_name:
          authType === "api_key" ? authHeaderName.trim() || "X-API-KEY" : null,
      };

      if (authSecret.trim()) {
        payload.auth_secret = authSecret.trim();
      }

      if (modalMode === "edit") {
        payload.clear_secret = clearCredentials || authType === "none";
      }

      const res = await fetch(endpoint, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });

      const json = await res.json().catch(() => null);

      if (!res.ok) {
        let msg = json?.detail || "Operation failed.";
        if (Array.isArray(msg)) msg = msg.map((m) => m.msg || m).join(", ");
        throw new Error(msg);
      }

      // Secure cleanup: clear secret from state immediately
      setAuthSecret("");
      setModalOpen(false);
      setSuccess(
        modalMode === "create"
          ? "Project created successfully with secure credentials!"
          : "Project updated successfully!"
      );
      setTimeout(() => setSuccess(""), 4000);
      await fetchProjects();

      // If updating currently selected project, update selection
      if (modalMode === "edit" && selectedProject?.id === editId && json?.data) {
        onSelectProject(json.data);
      }
    } catch (err) {
      setFormError(err.message || "Failed to save project.");
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = async (projectId) => {
    setError("");
    try {
      const res = await fetch(`${apiBaseUrl}/projects/${projectId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) {
        throw new Error("Failed to delete project.");
      }

      setDeleteConfirmId(null);
      setSuccess("Project deleted.");
      setTimeout(() => setSuccess(""), 4000);

      // Deselect if active project deleted
      if (selectedProject?.id === projectId) {
        onSelectProject(null);
      }

      await fetchProjects();
    } catch (err) {
      setError(err.message || "Failed to delete project.");
    }
  };

  const handleDiscoverEndpoints = async (proj) => {
    setDiscoveryModalOpen(true);
    setDiscoveredData(null);

    try {
      const res = await fetch(`${apiBaseUrl}/projects/${proj.id}/endpoints`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      const json = await res.json();
      if (!res.ok) {
        throw new Error(
          json.detail || "Failed to fetch endpoints from OpenAPI specification."
        );
      }

      setDiscoveredData(json.data);
    } catch (err) {
      setError(
        err.message || "Could not discover endpoints. Verify target API and OpenAPI URL."
      );
    }
  };

  return (
    <div className="page fade-in" style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* ── Page Header ── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 20,
          flexWrap: "wrap",
          gap: 16,
        }}
      >
        <div>
          <h1 className="page-title" style={{ fontSize: 24, fontWeight: 800 }}>
            API Projects & Workspaces
          </h1>
          <p className="page-sub">
            Organize APIs, configure AES-256 encrypted authentication, discover OpenAPI endpoints, and isolate test histories.
          </p>
        </div>
        <button className="btn btn-primary" onClick={openCreateModal}>
          <span>+</span>
          <span>New Project</span>
        </button>
      </div>

      {/* ── Notifications ── */}
      {error && (
        <div className="error-banner" style={{ margin: "0 0 18px" }}>
          <span>⚠ {error}</span>
          <button
            className="icon-btn"
            style={{ marginLeft: "auto", border: "none", background: "none" }}
            onClick={() => setError("")}
          >
            ✕
          </button>
        </div>
      )}
      {success && (
        <div className="success-banner" style={{ margin: "0 0 18px", padding: "10px 16px" }}>
          <span>✓ {success}</span>
        </div>
      )}

      {/* ── Active Testing Context Banner ── */}
      {selectedProject && (
        <div className="active-project-bar">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 20 }}>🎯</span>
            <div>
              <span
                style={{
                  fontSize: 10.5,
                  color: "var(--brand-primary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.8px",
                  fontWeight: 700,
                }}
              >
                Active Testing Context
              </span>
              <div style={{ fontWeight: 700, color: "var(--text-primary)", fontSize: 14 }}>
                {selectedProject.project_name}{" "}
                <span style={{ color: "var(--text-secondary)", fontWeight: 400, fontSize: 12 }}>
                  ({selectedProject.base_url})
                </span>
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: "6px 12px", fontSize: 12 }}
              onClick={() => handleDiscoverEndpoints(selectedProject)}
            >
              🔍 Discover Endpoints
            </button>
            <button
              type="button"
              className="btn btn-primary"
              style={{ padding: "6px 14px", fontSize: 12 }}
              onClick={() => onRunTestsWithProject(selectedProject)}
            >
              ▶ Run Tests Now
            </button>
          </div>
        </div>
      )}

      {/* ── Search & Filter Controls ── */}
      <div
        className="card"
        style={{
          marginBottom: 20,
          padding: "12px 18px",
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          alignItems: "center",
          justifyContent: "space-between",
          background: "var(--bg-subtle)",
        }}
      >
        {/* Search input */}
        <div style={{ position: "relative", flex: 1, minWidth: 240, maxWidth: 420 }}>
          <input
            type="text"
            className="input"
            placeholder="Search projects by name, URL, or auth mode..."
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

        {/* Sort selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 600 }}>
            Sort:
          </span>
          <select
            className="input"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{
              height: 34,
              fontSize: 12,
              padding: "4px 10px",
              background: "var(--bg-surface)",
              width: 140,
            }}
          >
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
            <option value="name">Name (A-Z)</option>
          </select>
        </div>
      </div>

      {/* ── Loading state ── */}
      {loading && (
        <div style={{ padding: 48, textAlign: "center", color: "var(--text-secondary)" }}>
          <div className="spinner" style={{ width: 24, height: 24, margin: "0 auto 12px" }} />
          Loading your API projects…
        </div>
      )}

      {/* ── Empty State ── */}
      {!loading && filteredAndSortedProjects.length === 0 && (
        <div className="empty-projects-card">
          <div className="empty-projects-icon">📁</div>
          <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8, color: "var(--text-primary)" }}>
            {searchTerm ? "No Matching Projects Found" : "No API Projects Yet"}
          </h3>
          <p
            style={{
              color: "var(--text-secondary)",
              fontSize: 13.5,
              maxWidth: 440,
              margin: "0 auto 20px",
              lineHeight: 1.5,
            }}
          >
            {searchTerm
              ? `No projects matched "${searchTerm}". Try resetting your search query.`
              : "Create your first project to configure your target API endpoint, OpenAPI schema, and secure authentication credentials."}
          </p>
          {searchTerm ? (
            <button className="btn btn-ghost" onClick={() => setSearchTerm("")}>
              Clear Search Filter
            </button>
          ) : (
            <button className="btn btn-primary" onClick={openCreateModal}>
              + Create First Project
            </button>
          )}
        </div>
      )}

      {/* ── Project Grid ── */}
      {!loading && filteredAndSortedProjects.length > 0 && (
        <div className="projects-grid">
          {filteredAndSortedProjects.map((proj) => {
            const isSelected = selectedProject?.id === proj.id;
            return (
              <div
                key={proj.id}
                className={`project-card ${isSelected ? "selected-project-card" : ""}`}
              >
                {/* Card Header */}
                <div className="project-card-header">
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div className="project-card-orb">⚡</div>
                    <div>
                      <h3 className="project-card-title">{proj.project_name}</h3>
                      <span className="project-date">
                        Created {new Date(proj.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  {isSelected ? (
                    <span className="active-tag">Active</span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      style={{ padding: "4px 10px", fontSize: 11 }}
                      onClick={() => onSelectProject(proj)}
                      title="Set as active workspace context"
                    >
                      Select
                    </button>
                  )}
                </div>

                {/* Description */}
                {proj.description ? (
                  <p className="project-desc">{proj.description}</p>
                ) : (
                  <p className="project-desc" style={{ color: "var(--text-muted)", fontStyle: "italic" }}>
                    No description provided.
                  </p>
                )}

                {/* Metadata & Endpoint Details */}
                <div className="project-endpoints-box">
                  <div className="pe-row">
                    <span className="pe-label">Base URL:</span>
                    <span className="pe-val" title={proj.base_url}>
                      {proj.base_url}
                    </span>
                  </div>
                  <div className="pe-row">
                    <span className="pe-label">OpenAPI:</span>
                    <span
                      className="pe-val"
                      title={proj.openapi_url || "Auto-detected <base_url>/openapi.json"}
                      style={{ color: proj.openapi_url ? "var(--brand-primary)" : "var(--text-secondary)" }}
                    >
                      {proj.openapi_url || "Auto-detected"}
                    </span>
                  </div>
                  <div className="pe-row" style={{ marginTop: 4, alignItems: "center" }}>
                    <span className="pe-label">Auth Mode:</span>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      {proj.auth_type === "bearer" ? (
                        <span
                          style={{
                            fontSize: 10.5,
                            background: "var(--brand-surface)",
                            color: "var(--brand-primary)",
                            border: "1px solid var(--brand-border)",
                            padding: "1px 6px",
                            borderRadius: "var(--r-xs)",
                            fontWeight: 600,
                          }}
                        >
                          Bearer Token
                        </span>
                      ) : proj.auth_type === "api_key" ? (
                        <span
                          style={{
                            fontSize: 10.5,
                            background: "rgba(168, 85, 247, 0.15)",
                            color: "#c084fc",
                            border: "1px solid rgba(168, 85, 247, 0.3)",
                            padding: "1px 6px",
                            borderRadius: "var(--r-xs)",
                            fontWeight: 600,
                          }}
                        >
                          {proj.auth_header_name || "API Key"}
                        </span>
                      ) : (
                        <span
                          style={{
                            fontSize: 10.5,
                            background: "var(--bg-subtle)",
                            color: "var(--text-muted)",
                            border: "1px solid var(--border-default)",
                            padding: "1px 6px",
                            borderRadius: "var(--r-xs)",
                          }}
                        >
                          Public API
                        </span>
                      )}

                      {proj.has_credentials ? (
                        <span
                          style={{ fontSize: 11, color: "var(--success)", fontWeight: 600 }}
                          title="Credentials encrypted with AES-256-GCM"
                        >
                          🔒 Encrypted
                        </span>
                      ) : proj.auth_type !== "none" ? (
                        <span style={{ fontSize: 11, color: "var(--danger)", fontWeight: 600 }}>
                          ⚠ No Secret Set
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>

                {/* Card Actions */}
                <div className="project-card-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    style={{ flex: 1, padding: "6px 10px", fontSize: 12 }}
                    onClick={() => {
                      onSelectProject(proj);
                      onRunTestsWithProject(proj);
                    }}
                  >
                    ▶ Run Tests
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    style={{ padding: "6px 10px", fontSize: 12 }}
                    title="Inspect discovered OpenAPI endpoints"
                    onClick={() => handleDiscoverEndpoints(proj)}
                  >
                    🔍 Endpoints
                  </button>
                  <button
                    type="button"
                    className="icon-btn"
                    title="Edit project"
                    onClick={() => openEditModal(proj)}
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    className="icon-btn delete-btn"
                    title="Delete project"
                    onClick={() => setDeleteConfirmId(proj.id)}
                  >
                    🗑
                  </button>
                </div>

                {/* Inline Delete Confirmation Overlay */}
                {deleteConfirmId === proj.id && (
                  <div className="delete-confirm-overlay fade-in">
                    <p style={{ fontSize: 13, color: "var(--text-primary)", marginBottom: 12, fontWeight: 600 }}>
                      Delete project <strong>"{proj.project_name}"</strong>?
                    </p>
                    <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 16 }}>
                      This will remove the workspace configuration and its associated credentials. Test history will remain preserved.
                    </p>
                    <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setDeleteConfirmId(null)}
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ background: "var(--danger)", color: "#fff" }}
                        onClick={() => handleDelete(proj.id)}
                      >
                        Yes, Delete
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Create / Edit Project Modal ── */}
      {modalOpen && (
        <div className="modal-backdrop" onClick={() => setModalOpen(false)}>
          <div
            className="modal-content"
            style={{ maxWidth: 580 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 style={{ fontSize: 17, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
                {modalMode === "create" ? "Create API Project Workspace" : "Edit API Project Workspace"}
              </h2>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setModalOpen(false)}
                aria-label="Close dialog"
              >
                ✕
              </button>
            </div>

            {formError && (
              <div className="error-banner" style={{ margin: "14px 22px 0" }}>
                ⚠ {formError}
              </div>
            )}

            <form onSubmit={handleFormSubmit} className="modal-form">
              {/* Section 1: General Info */}
              <div className="section-label" style={{ marginBottom: 4 }}>
                1. General Information
              </div>

              <div className="auth-field">
                <label>Project Name *</label>
                <input
                  type="text"
                  className="auth-input"
                  placeholder="e.g. Payment Gateway API"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  required
                />
              </div>

              <div className="auth-field">
                <label>Description (Optional)</label>
                <textarea
                  className="auth-input"
                  rows={2}
                  placeholder="Brief description of the API service, environment, or scope"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>

              {/* Section 2: API Configuration */}
              <div className="section-label" style={{ marginTop: 6, marginBottom: 4 }}>
                2. API Specification Endpoints
              </div>

              <div className="auth-field">
                <label>Target API Base URL *</label>
                <input
                  type="url"
                  className="auth-input"
                  placeholder="https://api.example.com or http://127.0.0.1:8000"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  required
                />
              </div>

              <div className="auth-field">
                <label>OpenAPI Specification URL (Optional)</label>
                <input
                  type="url"
                  className="auth-input"
                  placeholder="https://api.example.com/openapi.json"
                  value={openapiUrl}
                  onChange={(e) => setOpenapiUrl(e.target.value)}
                />
                <span style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                  Leave blank to auto-detect at &lt;base_url&gt;/openapi.json
                </span>
              </div>

              {/* Section 3: Target Authentication Vault */}
              <div className="section-label" style={{ marginTop: 6, marginBottom: 4 }}>
                3. Target Authentication Vault
              </div>

              <div
                style={{
                  padding: "14px 16px",
                  background: "var(--bg-subtle)",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--r-md)",
                }}
              >
                <div className="auth-field" style={{ marginBottom: 12 }}>
                  <label style={{ fontSize: 12 }}>Authentication Protocol</label>
                  <select
                    className="auth-input"
                    value={authType}
                    onChange={(e) => {
                      setAuthType(e.target.value);
                      setClearCredentials(false);
                    }}
                    style={{ background: "var(--bg-surface)", color: "var(--text-primary)" }}
                  >
                    <option value="none">Public API (No Authentication Required)</option>
                    <option value="bearer">Bearer Token (Authorization: Bearer &lt;token&gt;)</option>
                    <option value="api_key">Custom API Key Header (e.g. X-API-KEY)</option>
                  </select>
                </div>

                {/* API Key Header Name */}
                {authType === "api_key" && (
                  <div className="auth-field" style={{ marginBottom: 12 }}>
                    <label style={{ fontSize: 12 }}>Header Name *</label>
                    <input
                      type="text"
                      className="auth-input"
                      placeholder="e.g. X-API-KEY or X-Service-Token"
                      value={authHeaderName}
                      onChange={(e) => setAuthHeaderName(e.target.value)}
                      required={authType === "api_key"}
                    />
                    <span style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                      Only letters, numbers, hyphens, and underscores are allowed.
                    </span>
                  </div>
                )}

                {/* Secret Token / Key Input */}
                {authType !== "none" && (
                  <div className="auth-field">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <label style={{ fontSize: 12 }}>
                        {authType === "bearer" ? "Bearer Token Value *" : "API Key Secret Value *"}
                      </label>
                      <button
                        type="button"
                        onClick={() => setShowSecret(!showSecret)}
                        style={{
                          fontSize: 11,
                          padding: "2px 6px",
                          cursor: "pointer",
                          border: "none",
                          background: "none",
                          color: "var(--brand-primary)",
                          fontWeight: 600,
                        }}
                      >
                        {showSecret ? "Hide Secret" : "Show Secret"}
                      </button>
                    </div>

                    <div style={{ position: "relative" }}>
                      <input
                        type={showSecret ? "text" : "password"}
                        className="auth-input"
                        placeholder={
                          existingHasCredentials
                            ? "•••••••••••••••• (Leave blank to keep existing encrypted secret)"
                            : authType === "bearer"
                            ? "eyJhbGciOiJIUzI1NiIs..."
                            : "secret_api_key_..."
                        }
                        value={authSecret}
                        onChange={(e) => setAuthSecret(e.target.value)}
                        autoComplete="off"
                      />
                    </div>

                    {modalMode === "edit" && existingHasCredentials && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          marginTop: 8,
                          padding: "8px 10px",
                          background: "var(--bg-surface)",
                          borderRadius: "var(--r-sm)",
                          border: "1px solid var(--border-subtle)",
                          fontSize: 11.5,
                        }}
                      >
                        <span style={{ color: "var(--success)", fontWeight: 600 }}>
                          🔒 Encrypted with AES-256-GCM
                        </span>
                        <label
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 4,
                            cursor: "pointer",
                            color: "var(--danger)",
                            fontWeight: 600,
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={clearCredentials}
                            onChange={(e) => setClearCredentials(e.target.checked)}
                          />
                          Clear saved credential
                        </label>
                      </div>
                    )}

                    <span style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6, display: "block" }}>
                      🔒 Secrets are encrypted with AES-256-GCM before database insertion and never leaked in API responses.
                    </span>
                  </div>
                )}
              </div>

              {/* Modal Actions */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 14 }}>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setModalOpen(false)}
                  disabled={formLoading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={formLoading}
                >
                  {formLoading
                    ? "Saving Project…"
                    : modalMode === "create"
                    ? "Create Project"
                    : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Discovered OpenAPI Endpoint Explorer Modal ── */}
      {discoveryModalOpen && (
        <EndpointExplorer
          discoveredData={discoveredData}
          onClose={() => setDiscoveryModalOpen(false)}
          onRunTestsWithProject={onRunTestsWithProject}
        />
      )}
    </div>
  );
}
