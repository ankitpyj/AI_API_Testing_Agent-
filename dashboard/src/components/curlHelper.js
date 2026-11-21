/**
 * Safe cURL Command Generator
 * Enforces zero-credential leakage by omitting or masking sensitive secrets.
 */
export function generateSafeCurl(test, project, defaultBaseUrl = "http://127.0.0.1:8000") {
  if (!test || !test.endpoint) return null;

  const method = (test.method || "GET").toUpperCase();
  const rawBase = project?.base_url || defaultBaseUrl;
  const baseUrl = rawBase.replace(/\/+$/, "");
  const endpoint = test.endpoint.startsWith("/") ? test.endpoint : `/${test.endpoint}`;
  const fullUrl = test.endpoint.startsWith("http://") || test.endpoint.startsWith("https://")
    ? test.endpoint
    : `${baseUrl}${endpoint}`;

  const headers = [];

  // Content-Type header if request body exists
  let bodyPayload = null;
  if (test.request_body) {
    bodyPayload = test.request_body;
  } else if (test.request && typeof test.request === "object") {
    bodyPayload = test.request.body || test.request.payload || null;
  }

  if (bodyPayload || ["POST", "PUT", "PATCH"].includes(method)) {
    headers.push('-H "Content-Type: application/json"');
  }

  // Safe Authentication placeholder headers (NEVER real secrets)
  if (project?.auth_type === "bearer") {
    headers.push('-H "Authorization: Bearer <BEARER_TOKEN_OMITTED_FOR_SECURITY>"');
  } else if (project?.auth_type === "api_key") {
    const headerName = project.auth_header_name || "X-API-KEY";
    headers.push(`-H "${headerName}: <API_KEY_OMITTED_FOR_SECURITY>"`);
  }

  const parts = [`curl -X ${method} "${fullUrl}"`];
  headers.forEach((h) => parts.push(`  ${h}`));

  if (bodyPayload) {
    let bodyStr = typeof bodyPayload === "string" ? bodyPayload : JSON.stringify(bodyPayload);
    // Escape single quotes for shell safety
    bodyStr = bodyStr.replace(/'/g, "'\\''");
    parts.push(`  -d '${bodyStr}'`);
  }

  return parts.join(" \\\n");
}
