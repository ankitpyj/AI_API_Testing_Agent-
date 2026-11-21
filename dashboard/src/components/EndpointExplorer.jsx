import { useState, useMemo } from "react";

const getMethodColor = (method = "") => {
  const m = method.toUpperCase();
  switch (m) {
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

const getMethodBg = (method = "") => {
  const m = method.toUpperCase();
  switch (m) {
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

const getMethodBorder = (method = "") => {
  const m = method.toUpperCase();
  switch (m) {
    case "GET":
      return "var(--success-border)";
    case "POST":
      return "var(--brand-border)";
    case "PUT":
      return "var(--warning-border)";
    case "DELETE":
      return "var(--danger-border)";
    case "PATCH":
      return "rgba(139, 92, 246, 0.28)";
    default:
      return "var(--border-default)";
  }
};

export function EndpointExplorer({
  discoveredData,
  onClose,
  onRunTestsWithProject,
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedMethod, setSelectedMethod] = useState("ALL");
  const [expandedEndpoints, setExpandedEndpoints] = useState({});

  const endpoints = useMemo(() => discoveredData?.endpoints || [], [discoveredData?.endpoints]);

  // Extract distinct HTTP methods available in this spec
  const availableMethods = useMemo(() => {
    const set = new Set(endpoints.map((e) => e.method));
    return ["ALL", ...Array.from(set)];
  }, [endpoints]);

  // Filter endpoints
  const filteredEndpoints = useMemo(() => {
    return endpoints.filter((ep) => {
      const matchesMethod =
        selectedMethod === "ALL" || ep.method === selectedMethod;
      const term = searchTerm.toLowerCase().trim();
      const matchesSearch =
        !term ||
        ep.path.toLowerCase().includes(term) ||
        (ep.summary && ep.summary.toLowerCase().includes(term));
      return matchesMethod && matchesSearch;
    });
  }, [endpoints, selectedMethod, searchTerm]);

  // Group filtered endpoints by primary resource prefix (e.g. /users, /auth, /items)
  const groupedEndpoints = useMemo(() => {
    const groups = {};
    filteredEndpoints.forEach((ep) => {
      const parts = ep.path.split("/").filter(Boolean);
      let groupKey = "/";
      if (parts.length > 0) {
        // e.g. /users, /auth, /projects
        groupKey = `/${parts[0]}`;
      }
      if (!groups[groupKey]) {
        groups[groupKey] = [];
      }
      groups[groupKey].push(ep);
    });
    return groups;
  }, [filteredEndpoints]);

  const toggleExpand = (key) => {
    setExpandedEndpoints((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const expandAll = () => {
    const all = {};
    endpoints.forEach((_, idx) => {
      all[idx] = true;
    });
    setExpandedEndpoints(all);
  };

  const collapseAll = () => {
    setExpandedEndpoints({});
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-content endpoint-explorer-modal"
        style={{ maxWidth: 860, width: "95%" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="modal-header" style={{ padding: "18px 24px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              className="project-card-orb"
              style={{
                background: "var(--brand-surface)",
                borderColor: "var(--brand-border)",
                fontSize: 18,
              }}
            >
              🔍
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h2 style={{ fontSize: 17, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
                  OpenAPI Endpoint Explorer
                </h2>
                <span
                  style={{
                    fontSize: 10.5,
                    fontWeight: 700,
                    padding: "2px 7px",
                    borderRadius: "var(--r-full)",
                    background:
                      discoveredData?.auth_type !== "none"
                        ? "var(--brand-surface)"
                        : "var(--bg-subtle)",
                    color:
                      discoveredData?.auth_type !== "none"
                        ? "var(--brand-primary)"
                        : "var(--text-muted)",
                    border: `1px solid ${
                      discoveredData?.auth_type !== "none"
                        ? "var(--brand-border)"
                        : "var(--border-default)"
                    }`,
                    textTransform: "uppercase",
                  }}
                >
                  {discoveredData?.auth_type === "bearer"
                    ? "🔒 Bearer Token Auth"
                    : discoveredData?.auth_type === "api_key"
                    ? `🔒 ${discoveredData.auth_header_name || "API-Key"}`
                    : "🌐 Public API"}
                </span>
              </div>
              <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
                {discoveredData?.project_name} &bull;{" "}
                <span style={{ fontFamily: "var(--mono)", color: "var(--brand-primary)" }}>
                  {discoveredData?.openapi_url}
                </span>
              </p>
            </div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </div>

        {/* Search & Filter Toolbar */}
        <div
          style={{
            padding: "12px 24px",
            borderBottom: "1px solid var(--border-default)",
            background: "var(--bg-subtle)",
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          {/* Search Field */}
          <div style={{ position: "relative", flex: 1, minWidth: 220 }}>
            <input
              type="text"
              className="auth-input"
              placeholder="Search by endpoint path or summary..."
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
          </div>

          {/* HTTP Method Filters */}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {availableMethods.map((m) => (
              <button
                key={m}
                type="button"
                className={`filter-tab ${selectedMethod === m ? "active" : ""}`}
                onClick={() => setSelectedMethod(m)}
                style={{
                  height: 30,
                  padding: "0 10px",
                  fontSize: 11,
                  fontWeight: 700,
                  color: selectedMethod === m ? "var(--text-primary)" : getMethodColor(m),
                }}
              >
                {m}
              </button>
            ))}
          </div>

          {/* Collapse/Expand Controls */}
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ height: 30, fontSize: 11, padding: "0 8px" }}
              onClick={expandAll}
            >
              Expand All
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ height: 30, fontSize: 11, padding: "0 8px" }}
              onClick={collapseAll}
            >
              Collapse
            </button>
          </div>
        </div>

        {/* Endpoint List Body */}
        <div
          style={{
            padding: "16px 24px",
            maxHeight: "58vh",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
          className="custom-scroll"
        >
          {filteredEndpoints.length === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 16px", color: "var(--text-muted)" }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>🔍</div>
              <p style={{ margin: 0, fontSize: 13.5 }}>
                No endpoints match your search criteria.
              </p>
            </div>
          ) : (
            Object.entries(groupedEndpoints).map(([groupKey, groupEps]) => (
              <div key={groupKey} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {/* Resource Group Header */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "4px 2px",
                    borderBottom: "1px solid var(--border-subtle)",
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 11.5,
                      fontWeight: 700,
                      color: "var(--brand-primary)",
                      letterSpacing: 0.5,
                      textTransform: "uppercase",
                    }}
                  >
                    Resource: {groupKey}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      background: "var(--bg-subtle)",
                      border: "1px solid var(--border-default)",
                      padding: "1px 6px",
                      borderRadius: "var(--r-full)",
                      color: "var(--text-muted)",
                    }}
                  >
                    {groupEps.length}
                  </span>
                </div>

                {/* Endpoints in Group */}
                {groupEps.map((ep, idx) => {
                  const globalIdx = `${groupKey}-${idx}`;
                  const isExpanded = Boolean(expandedEndpoints[globalIdx]);
                  const pathParams = (ep.path.match(/\{([^}]+)\}/g) || []).map((p) =>
                    p.replace(/[{}]/g, "")
                  );

                  return (
                    <div
                      key={globalIdx}
                      style={{
                        background: "var(--bg-surface)",
                        border: `1px solid ${
                          isExpanded ? "var(--brand-border)" : "var(--border-default)"
                        }`,
                        borderRadius: "var(--r-md)",
                        overflow: "hidden",
                        transition: "var(--t)",
                      }}
                    >
                      {/* Clickable Row Header */}
                      <div
                        onClick={() => toggleExpand(globalIdx)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "10px 14px",
                          cursor: "pointer",
                          gap: 12,
                          background: isExpanded ? "var(--brand-surface)" : "transparent",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            minWidth: 0,
                            flex: 1,
                          }}
                        >
                          {/* Method Badge */}
                          <span
                            style={{
                              fontFamily: "var(--mono)",
                              fontSize: 10.5,
                              fontWeight: 700,
                              padding: "2px 8px",
                              borderRadius: "var(--r-xs)",
                              background: getMethodBg(ep.method),
                              border: `1px solid ${getMethodBorder(ep.method)}`,
                              color: getMethodColor(ep.method),
                              minWidth: 54,
                              textAlign: "center",
                            }}
                          >
                            {ep.method}
                          </span>

                          {/* Path */}
                          <span
                            style={{
                              fontFamily: "var(--mono)",
                              fontSize: 12.5,
                              fontWeight: 600,
                              color: "var(--text-primary)",
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {ep.path}
                          </span>

                          {/* Summary preview */}
                          {ep.summary && (
                            <span
                              style={{
                                fontSize: 11.5,
                                color: "var(--text-muted)",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                marginLeft: 4,
                              }}
                            >
                              — {ep.summary}
                            </span>
                          )}
                        </div>

                        {/* Right side indicators */}
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                          {ep.requires_body && (
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 600,
                                padding: "1px 6px",
                                borderRadius: "var(--r-xs)",
                                background: "var(--bg-subtle)",
                                border: "1px solid var(--border-default)",
                                color: "var(--text-secondary)",
                              }}
                            >
                              Body
                            </span>
                          )}

                          <span
                            style={{
                              fontSize: 11,
                              color: "var(--text-muted)",
                              transition: "transform 0.2s ease",
                              transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                            }}
                          >
                            ▼
                          </span>
                        </div>
                      </div>

                      {/* Expanded Technical Inspection Details */}
                      {isExpanded && (
                        <div
                          className="fade-in"
                          style={{
                            padding: "14px 18px",
                            borderTop: "1px solid var(--border-subtle)",
                            background: "var(--bg-subtle)",
                            display: "flex",
                            flexDirection: "column",
                            gap: 12,
                          }}
                        >
                          {/* Endpoint Summary */}
                          {ep.summary && (
                            <div>
                              <div className="diff-label">Description / Summary</div>
                              <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                                {ep.summary}
                              </p>
                            </div>
                          )}

                          {/* Parameters Inspection */}
                          <div>
                            <div className="diff-label">Parameters</div>
                            {pathParams.length > 0 ? (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                                {pathParams.map((paramName) => (
                                  <div
                                    key={paramName}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: 6,
                                      padding: "4px 10px",
                                      borderRadius: "var(--r-sm)",
                                      background: "var(--bg-surface)",
                                      border: "1px solid var(--border-default)",
                                      fontSize: 11.5,
                                    }}
                                  >
                                    <span style={{ fontFamily: "var(--mono)", color: "var(--brand-primary)", fontWeight: 700 }}>
                                      {paramName}
                                    </span>
                                    <span style={{ color: "var(--text-muted)", fontSize: 10 }}>in path</span>
                                    <span style={{ color: "var(--danger)", fontSize: 10, fontWeight: 700 }}>*required</span>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <span style={{ fontSize: 12, color: "var(--text-muted)", fontStyle: "italic", marginTop: 4, display: "block" }}>
                                No path parameters required.
                              </span>
                            )}
                          </div>

                          {/* Request Body Specification */}
                          <div>
                            <div className="diff-label">Request Body Payload</div>
                            <div style={{ marginTop: 6 }}>
                              {ep.requires_body ? (
                                <div
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    padding: "6px 12px",
                                    borderRadius: "var(--r-sm)",
                                    background: "var(--bg-surface)",
                                    border: "1px solid var(--border-default)",
                                    fontSize: 12,
                                    color: "var(--text-secondary)",
                                  }}
                                >
                                  <span style={{ color: "var(--warning)", fontWeight: 700 }}>●</span>
                                  <span>
                                    <strong>Content-Type: application/json</strong>. Required body schemas are extracted and synthesized during automated test execution.
                                  </span>
                                </div>
                              ) : (
                                <span style={{ fontSize: 12, color: "var(--text-muted)", fontStyle: "italic" }}>
                                  No request body required for {ep.method} requests.
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Responses Specification */}
                          <div>
                            <div className="diff-label">Expected Responses</div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                              {ep.responses && ep.responses.length > 0 ? (
                                ep.responses.map((statusCode) => {
                                  const isSuccess = statusCode.startsWith("2");
                                  const isRedirect = statusCode.startsWith("3");
                                  const isClientErr = statusCode.startsWith("4");
                                  return (
                                    <span
                                      key={statusCode}
                                      style={{
                                        fontFamily: "var(--mono)",
                                        fontSize: 11,
                                        fontWeight: 700,
                                        padding: "2px 8px",
                                        borderRadius: "var(--r-xs)",
                                        background: isSuccess
                                          ? "var(--success-surface)"
                                          : isRedirect
                                          ? "var(--warning-surface)"
                                          : isClientErr
                                          ? "var(--danger-surface)"
                                          : "var(--bg-surface)",
                                        border: `1px solid ${
                                          isSuccess
                                            ? "var(--success-border)"
                                            : isRedirect
                                            ? "var(--warning-border)"
                                            : isClientErr
                                            ? "var(--danger-border)"
                                            : "var(--border-default)"
                                        }`,
                                        color: isSuccess
                                          ? "var(--success)"
                                          : isRedirect
                                          ? "var(--warning)"
                                          : isClientErr
                                          ? "var(--danger)"
                                          : "var(--text-secondary)",
                                      }}
                                    >
                                      HTTP {statusCode}
                                    </span>
                                  );
                                })
                              ) : (
                                <span style={{ fontSize: 12, color: "var(--text-muted)", fontStyle: "italic" }}>
                                  Status codes not explicitly enumerated in OpenAPI spec.
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: "14px 24px",
            borderTop: "1px solid var(--border-default)",
            background: "var(--bg-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Showing {filteredEndpoints.length} of {discoveredData?.total_endpoints || 0} endpoints
          </span>

          <div style={{ display: "flex", gap: 10 }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Close
            </button>
            {onRunTestsWithProject && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  onClose();
                  onRunTestsWithProject({
                    id: discoveredData.project_id,
                    project_name: discoveredData.project_name,
                    base_url: discoveredData.base_url,
                    openapi_url: discoveredData.openapi_url,
                    auth_type: discoveredData.auth_type,
                    auth_header_name: discoveredData.auth_header_name,
                    has_credentials: discoveredData.has_credentials,
                  });
                }}
              >
                ▶ Run Tests on Project
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
