import { useState } from "react";

export function AuthPage({ apiBaseUrl, onLoginSuccess }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  
  // Form states
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  
  // Show / Hide password toggles
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  
  // Status states
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const resetForm = (targetMode) => {
    setMode(targetMode);
    setError("");
    setSuccessMsg("");
    setPassword("");
    setConfirmPassword("");
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setSuccessMsg("");

    if (!email.trim() || !password) {
      setError("Please enter your email and password.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${apiBaseUrl}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          password,
        }),
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        const errorDetail = data?.detail || "Invalid email or password.";
        throw new Error(errorDetail);
      }

      if (data?.data?.access_token && data?.data?.user) {
        onLoginSuccess(data.data.access_token, data.data.user);
      } else {
        throw new Error("Invalid response received from authentication server.");
      }
    } catch (err) {
      setError(err.message || "Failed to log in. Please check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    setError("");
    setSuccessMsg("");

    if (!fullName.trim()) {
      setError("Full name is required.");
      return;
    }
    if (!email.trim()) {
      setError("Email address is required.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${apiBaseUrl}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName.trim(),
          email: email.trim(),
          password,
          confirm_password: confirmPassword,
        }),
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        let msg = data?.detail || "Registration failed.";
        if (Array.isArray(msg)) {
          msg = msg.map(item => item.msg || item).join(", ");
        }
        throw new Error(msg);
      }

      if (data?.data?.access_token && data?.data?.user) {
        onLoginSuccess(data.data.access_token, data.data.user);
      } else {
        setSuccessMsg("Account created! Please log in.");
        resetForm("login");
      }
    } catch (err) {
      setError(err.message || "Failed to register account.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        {/* Brand Header */}
        <div className="auth-header">
          <div className="logo-orb auth-logo-orb">🤖</div>
          <h1 className="auth-title">AI Test Agent</h1>
          <p className="auth-subtitle">
            {mode === "login"
              ? "Sign in to access your automated API testing workspace"
              : "Create an account to start automated API test generation"}
          </p>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="error-banner auth-alert">
            <span>⚠ {error}</span>
            <button
              type="button"
              className="icon-btn"
              style={{ marginLeft: "auto", border: "none", background: "none" }}
              onClick={() => setError("")}
            >
              ✕
            </button>
          </div>
        )}

        {/* Success Banner */}
        {successMsg && (
          <div className="success-banner auth-alert">
            <span>✓ {successMsg}</span>
          </div>
        )}

        {/* Login Form */}
        {mode === "login" && (
          <form onSubmit={handleLogin} className="auth-form" noValidate>
            <div className="auth-field">
              <label htmlFor="login-email">Email Address</label>
              <input
                id="login-email"
                type="email"
                className="auth-input"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="auth-field">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <label htmlFor="login-password">Password</label>
              </div>
              <div className="auth-input-wrapper">
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  className="auth-input"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  title={showPassword ? "Hide password" : "Show password"}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "👁" : "👁‍🗨"}
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary auth-submit-btn"
              disabled={loading}
            >
              {loading ? (
                <>
                  <div className="spinner" style={{ width: 14, height: 14 }} />
                  Signing In…
                </>
              ) : (
                "Sign In"
              )}
            </button>

            <div className="auth-switch">
              <span>Don't have an account?</span>{" "}
              <button
                type="button"
                className="auth-switch-btn"
                onClick={() => resetForm("signup")}
              >
                Create Account
              </button>
            </div>
          </form>
        )}

        {/* Signup Form */}
        {mode === "signup" && (
          <form onSubmit={handleSignup} className="auth-form" noValidate>
            <div className="auth-field">
              <label htmlFor="signup-name">Full Name</label>
              <input
                id="signup-name"
                type="text"
                className="auth-input"
                placeholder="Jane Doe"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                autoComplete="name"
                required
              />
            </div>

            <div className="auth-field">
              <label htmlFor="signup-email">Work Email</label>
              <input
                id="signup-email"
                type="email"
                className="auth-input"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="auth-field">
              <label htmlFor="signup-password">Password (min. 8 characters)</label>
              <div className="auth-input-wrapper">
                <input
                  id="signup-password"
                  type={showPassword ? "text" : "password"}
                  className="auth-input"
                  placeholder="Create a secure password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  title={showPassword ? "Hide password" : "Show password"}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "👁" : "👁‍🗨"}
                </button>
              </div>
            </div>

            <div className="auth-field">
              <label htmlFor="signup-confirm">Confirm Password</label>
              <div className="auth-input-wrapper">
                <input
                  id="signup-confirm"
                  type={showConfirmPassword ? "text" : "password"}
                  className="auth-input"
                  placeholder="Re-enter password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  title={showConfirmPassword ? "Hide password" : "Show password"}
                  aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                >
                  {showConfirmPassword ? "👁" : "👁‍🗨"}
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary auth-submit-btn"
              disabled={loading}
            >
              {loading ? (
                <>
                  <div className="spinner" style={{ width: 14, height: 14 }} />
                  Creating Account…
                </>
              ) : (
                "Create Account"
              )}
            </button>

            <div className="auth-switch">
              <span>Already have an account?</span>{" "}
              <button
                type="button"
                className="auth-switch-btn"
                onClick={() => resetForm("login")}
              >
                Sign In
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
