import { useState, useMemo } from "react";

/**
 * Safely parse a value if it's a JSON string.
 */
const safeParseJson = (val) => {
  if (val == null) return null;
  if (typeof val === "object") return val;
  if (typeof val !== "string") return val;
  const trimmed = val.trim();
  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return val;
    }
  }
  return val;
};

/**
 * Deep structural diff computation between Expected and Actual JSON data.
 */
function computeJsonDiff(expected, actual) {
  // If either is not an object or is null/array
  if (
    expected === null ||
    actual === null ||
    typeof expected !== "object" ||
    typeof actual !== "object" ||
    Array.isArray(expected) ||
    Array.isArray(actual)
  ) {
    const isMatch = JSON.stringify(expected) === JSON.stringify(actual);
    return {
      isLeaf: true,
      expected,
      actual,
      status: isMatch ? "same" : "changed",
    };
  }

  const allKeys = Array.from(
    new Set([...Object.keys(expected || {}), ...Object.keys(actual || {})])
  );

  const diffObj = {};
  allKeys.forEach((key) => {
    const inExp = expected != null && key in expected;
    const inAct = actual != null && key in actual;

    if (inExp && !inAct) {
      diffObj[key] = {
        status: "removed",
        expected: expected[key],
        actual: undefined,
      };
    } else if (!inExp && inAct) {
      diffObj[key] = {
        status: "added",
        expected: undefined,
        actual: actual[key],
      };
    } else {
      const expVal = expected[key];
      const actVal = actual[key];

      if (
        typeof expVal === "object" &&
        expVal !== null &&
        typeof actVal === "object" &&
        actVal !== null
      ) {
        if (Array.isArray(expVal) || Array.isArray(actVal)) {
          const match = JSON.stringify(expVal) === JSON.stringify(actVal);
          diffObj[key] = {
            status: match ? "same" : "changed",
            expected: expVal,
            actual: actVal,
            isLeaf: true,
          };
        } else {
          diffObj[key] = {
            status: "nested",
            children: computeJsonDiff(expVal, actVal),
          };
        }
      } else {
        const match = expVal === actVal;
        diffObj[key] = {
          status: match ? "same" : "changed",
          expected: expVal,
          actual: actVal,
          isLeaf: true,
        };
      }
    }
  });

  return { isLeaf: false, diffObj };
}

/**
 * Render visual diff line items.
 */
function RenderDiffTree({ node, indent = 1 }) {
  if (!node) return null;

  if (node.isLeaf) {
    const color =
      node.status === "added"
        ? "var(--success)"
        : node.status === "removed"
        ? "var(--danger)"
        : node.status === "changed"
        ? "var(--warning)"
        : "var(--text-secondary)";

    return (
      <div style={{ paddingLeft: indent * 16, fontFamily: "var(--mono)", fontSize: 11.5, color }}>
        {node.status === "changed" && (
          <div>
            <span style={{ color: "var(--danger)" }}>- {JSON.stringify(node.expected)}</span>
            <br />
            <span style={{ color: "var(--success)" }}>+ {JSON.stringify(node.actual)}</span>
          </div>
        )}
        {node.status === "same" && <span>{JSON.stringify(node.expected)}</span>}
      </div>
    );
  }

  const entries = Object.entries(node.diffObj || {});

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {entries.map(([key, val]) => {
        const status = val.status;
        let prefix = "  ";
        let color = "var(--text-secondary)";
        let bg = "transparent";

        if (status === "added") {
          prefix = "+ ";
          color = "var(--success)";
          bg = "var(--success-surface)";
        } else if (status === "removed") {
          prefix = "- ";
          color = "var(--danger)";
          bg = "var(--danger-surface)";
        } else if (status === "changed") {
          prefix = "~ ";
          color = "var(--warning)";
          bg = "var(--warning-surface)";
        }

        if (status === "nested") {
          return (
            <div key={key} style={{ paddingLeft: indent * 14 }}>
              <span style={{ fontFamily: "var(--mono)", color: "var(--text-primary)", fontWeight: 600, fontSize: 12 }}>
                "{key}": &#123;
              </span>
              <RenderDiffTree node={val.children} indent={indent + 1} />
              <span style={{ fontFamily: "var(--mono)", color: "var(--text-primary)", fontSize: 12 }}>
                &#125;
              </span>
            </div>
          );
        }

        return (
          <div
            key={key}
            style={{
              paddingLeft: indent * 14,
              paddingRight: 8,
              paddingTop: 2,
              paddingBottom: 2,
              borderRadius: "var(--r-xs)",
              background: bg,
              fontFamily: "var(--mono)",
              fontSize: 12,
              lineHeight: 1.5,
              wordBreak: "break-all",
            }}
          >
            <span style={{ color, fontWeight: 700, marginRight: 6 }}>{prefix}</span>
            <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>"{key}": </span>
            {status === "changed" ? (
              <span>
                <span style={{ color: "var(--danger)", textDecoration: "line-through", marginRight: 8 }}>
                  {JSON.stringify(val.expected)}
                </span>
                <span style={{ color: "var(--success)", fontWeight: 600 }}>
                  {JSON.stringify(val.actual)}
                </span>
              </span>
            ) : status === "removed" ? (
              <span style={{ color: "var(--danger)" }}>
                {JSON.stringify(val.expected)}
              </span>
            ) : status === "added" ? (
              <span style={{ color: "var(--success)" }}>
                {JSON.stringify(val.actual)}
              </span>
            ) : (
              <span style={{ color: "var(--text-secondary)" }}>
                {JSON.stringify(val.expected)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Reusable JSON Diff Viewer Component
 */
export function JsonDiffViewer({
  expectedBody,
  actualBody,
  expectedLabel = "Expected Response Body",
  actualLabel = "Actual Response Body",
}) {
  const [viewMode, setViewMode] = useState("split"); // "split" | "diff"
  const [copiedExp, setCopiedExp] = useState(false);
  const [copiedAct, setCopiedAct] = useState(false);

  const parsedExp = useMemo(() => safeParseJson(expectedBody), [expectedBody]);
  const parsedAct = useMemo(() => safeParseJson(actualBody), [actualBody]);

  const formattedExp = useMemo(() => {
    if (parsedExp == null) return null;
    if (typeof parsedExp === "object" && !Array.isArray(parsedExp) && Object.keys(parsedExp).length === 0) {
      return null;
    }
    return typeof parsedExp === "object" ? JSON.stringify(parsedExp, null, 2) : String(parsedExp);
  }, [parsedExp]);

  const formattedAct = useMemo(() => {
    if (parsedAct == null) return "—";
    return typeof parsedAct === "object" ? JSON.stringify(parsedAct, null, 2) : String(parsedAct);
  }, [parsedAct]);

  const diffTree = useMemo(() => {
    if (parsedExp == null || parsedAct == null) return null;
    return computeJsonDiff(parsedExp, parsedAct);
  }, [parsedExp, parsedAct]);

  const handleCopyExp = () => {
    if (!formattedExp) return;
    navigator.clipboard.writeText(formattedExp);
    setCopiedExp(true);
    setTimeout(() => setCopiedExp(false), 2000);
  };

  const handleCopyAct = () => {
    if (!formattedAct) return;
    navigator.clipboard.writeText(formattedAct);
    setCopiedAct(true);
    setTimeout(() => setCopiedAct(false), 2000);
  };

  return (
    <div className="json-diff-container" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* View Mode & Action Controls */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 2,
        }}
      >
        <div style={{ display: "flex", gap: 4 }}>
          <button
            type="button"
            className={`filter-tab ${viewMode === "split" ? "active" : ""}`}
            onClick={() => setViewMode("split")}
            style={{ fontSize: 11, padding: "2px 10px" }}
          >
            Side-by-Side
          </button>
          <button
            type="button"
            className={`filter-tab ${viewMode === "diff" ? "active" : ""}`}
            onClick={() => setViewMode("diff")}
            style={{ fontSize: 11, padding: "2px 10px" }}
            disabled={!diffTree}
          >
            Structural Diff
          </button>
        </div>

        <div style={{ display: "flex", gap: 6 }}>
          {formattedExp && (
            <button
              type="button"
              className="shortcut-btn"
              onClick={handleCopyExp}
              title="Copy formatted expected JSON"
              style={{ fontSize: 11, padding: "2px 8px" }}
            >
              {copiedExp ? "✓ Expected Copied" : "Copy Expected"}
            </button>
          )}
          <button
            type="button"
            className="shortcut-btn"
            onClick={handleCopyAct}
            title="Copy formatted actual JSON"
            style={{ fontSize: 11, padding: "2px 8px" }}
          >
            {copiedAct ? "✓ Actual Copied" : "Copy Actual"}
          </button>
        </div>
      </div>

      {/* Structural Diff View */}
      {viewMode === "diff" && diffTree ? (
        <div
          className="code-pre custom-scroll"
          style={{
            maxHeight: 280,
            overflowY: "auto",
            background: "var(--bg-subtle)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--r-sm)",
            padding: "12px 14px",
          }}
        >
          <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginBottom: 8, fontStyle: "italic" }}>
            Key: <span style={{ color: "var(--success)" }}>+ Added in Actual</span> &bull;{" "}
            <span style={{ color: "var(--danger)" }}>- Missing in Actual</span> &bull;{" "}
            <span style={{ color: "var(--warning)" }}>~ Value Mismatch</span>
          </div>
          <span style={{ fontFamily: "var(--mono)", color: "var(--text-primary)" }}>&#123;</span>
          <RenderDiffTree node={diffTree} indent={1} />
          <span style={{ fontFamily: "var(--mono)", color: "var(--text-primary)" }}>&#125;</span>
        </div>
      ) : (
        /* Side-by-Side View */
        <div className="body-diff" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="diff-block">
            <div className="diff-label" style={{ display: "flex", justifyContent: "space-between" }}>
              <span>📤 {expectedLabel}</span>
            </div>
            {formattedExp ? (
              <pre className="code-pre custom-scroll" style={{ maxHeight: 240, overflowY: "auto" }}>
                {formattedExp}
              </pre>
            ) : (
              <pre
                className="code-pre"
                style={{
                  color: "var(--text-muted)",
                  fontStyle: "italic",
                  maxHeight: 240,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                Not specified in OpenAPI specification
              </pre>
            )}
          </div>

          <div className="diff-block">
            <div className="diff-label" style={{ display: "flex", justifyContent: "space-between" }}>
              <span>📥 {actualLabel}</span>
            </div>
            <pre className="code-pre custom-scroll" style={{ maxHeight: 240, overflowY: "auto" }}>
              {formattedAct}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
