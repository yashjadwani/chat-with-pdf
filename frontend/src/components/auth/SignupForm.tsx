import { FormEvent, useState } from "react";
import { ArrowRight, Eye, EyeOff, LockKeyhole, Mail, Sparkles, UserRound } from "lucide-react";
import { supabase } from "../../lib/supabase";
import { logger } from "../../lib/logger";
import { Button } from "../ui/Button";

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function SignupForm({
  onModeChange,
  onVerificationNeeded
}: {
  onModeChange: () => void;
  onVerificationNeeded: (email: string) => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [existingAccountEmail, setExistingAccountEmail] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const emailIsInvalid = email.length > 0 && !emailPattern.test(email.trim());
  const passwordsDoNotMatch = confirmPassword.length > 0 && password !== confirmPassword;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setExistingAccountEmail("");
    setSuccess(false);
    const trimmedEmail = email.trim();

    if (!emailPattern.test(trimmedEmail)) {
      setMessage("Enter a valid email address.");
      setLoading(false);
      return;
    }

    if (passwordsDoNotMatch) {
      setMessage("Passwords do not match.");
      setLoading(false);
      return;
    }

    const { data, error } = await supabase.auth.signUp({
      email: trimmedEmail,
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/app`,
        data: {
          display_name: displayName.trim()
        }
      }
    });
    logger.info("auth_signup_response", {
      hasError: Boolean(error),
      hasSession: Boolean(data.session),
      hasUserEmail: Boolean(getSignupResponseEmail(data)),
      identityCount: getSignupResponseIdentityCount(data)
    });
    if (isExistingSignupResponse(data)) {
      logger.warn("auth_signup_existing_account", { source: "silent_success" });
      setExistingAccountEmail(trimmedEmail);
      setMessage("");
      setSuccess(false);
    } else if (error) {
      if (isExistingAccountMessage(error.message)) {
        logger.warn("auth_signup_existing_account", { source: "auth_error" });
        setExistingAccountEmail(trimmedEmail);
        setMessage("");
      } else {
        logger.warn("auth_signup_failed", { reason: normalizeAuthReason(error.message) });
        setMessage(error.message);
      }
      setSuccess(false);
    } else {
      if (data.session) await supabase.auth.signOut();
      logger.info("auth_signup_verification_required", { hasSession: Boolean(data.session) });
      setSuccess(true);
      onVerificationNeeded(trimmedEmail);
    }
    setLoading(false);
  }

  function goToLogin() {
    setExistingAccountEmail("");
    onModeChange();
  }

  return (
    <>
    <form className="auth-form" onSubmit={onSubmit}>
      <div className="form-heading">
        <Sparkles size={22} />
        <div>
          <h1>Create account</h1>
          <p>Start a private place for your documents and questions.</p>
        </div>
      </div>

      <label className="field-group">
        <span className="field-label">Name</span>
        <span className="input-shell">
          <UserRound size={17} />
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            type="text"
            autoComplete="name"
            required
          />
        </span>
      </label>
      <label className="field-group">
        <span className="field-label">Email</span>
        <span className="input-shell">
          <Mail size={17} />
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            type="email"
            autoComplete="email"
            required
          />
        </span>
        {emailIsInvalid && <span className="field-error">Enter a valid email address.</span>}
      </label>

      <label className="field-group">
        <span className="field-label">Password</span>
        <span className="input-shell">
          <LockKeyhole size={17} />
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            minLength={6}
            required
          />
          <button
            className="input-icon-button"
            type="button"
            onClick={() => setShowPassword((current) => !current)}
            aria-label={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        </span>
      </label>

      <label className="field-group">
        <span className="field-label">Confirm password</span>
        <span className="input-shell">
          <LockKeyhole size={17} />
          <input
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            type={showConfirmPassword ? "text" : "password"}
            autoComplete="new-password"
            minLength={6}
            required
          />
          <button
            className="input-icon-button"
            type="button"
            onClick={() => setShowConfirmPassword((current) => !current)}
            aria-label={showConfirmPassword ? "Hide confirm password" : "Show confirm password"}
          >
            {showConfirmPassword ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        </span>
        {passwordsDoNotMatch && <span className="field-error">Passwords do not match.</span>}
      </label>

      <div className="form-message-slot" aria-live="polite">
        {existingAccountEmail ? (
          <div className="account-exists-callout" role="alert">
            <strong>You already have an account.</strong>
            <span>{existingAccountEmail} is already registered. Try logging in instead.</span>
            <button className="text-button account-login-link" type="button" onClick={goToLogin}>
              Go to login
            </button>
          </div>
        ) : message ? (
          <p className={success ? "form-note form-success" : "form-error"}>{message}</p>
        ) : null}
      </div>

      <Button disabled={loading || emailIsInvalid || passwordsDoNotMatch} type="submit">
        {loading ? "Creating" : "Create account"}
        <ArrowRight size={17} />
      </Button>

      <button className="text-button auth-switch-link" type="button" onClick={onModeChange}>
        Already have an account?
      </button>
    </form>
    {existingAccountEmail ? (
      <div className="auth-modal-backdrop" role="presentation">
        <section className="account-exists-dialog" role="alertdialog" aria-modal="true" aria-labelledby="account-exists-title">
          <span className="account-exists-icon" aria-hidden="true">
            <Mail size={22} />
          </span>
          <div>
            <h2 id="account-exists-title">You already have an account</h2>
            <p>
              <strong>{existingAccountEmail}</strong> is already registered. Log in instead to open your PDF Chat workspace.
            </p>
          </div>
          <div className="account-exists-actions">
            <Button type="button" onClick={goToLogin}>
              Go to login
              <ArrowRight size={17} />
            </Button>
          </div>
        </section>
      </div>
    ) : null}
    </>
  );
}

function getSignupResponseIdentities(data: unknown) {
  if (!data || typeof data !== "object") return undefined;

  const response = data as { identities?: unknown; user?: { identities?: unknown } | null };
  return response.user?.identities ?? response.identities;
}

function getSignupResponseIdentityCount(data: unknown) {
  const identities = getSignupResponseIdentities(data);
  return Array.isArray(identities) ? identities.length : null;
}

function getSignupResponseEmail(data: unknown) {
  if (!data || typeof data !== "object") return undefined;

  const response = data as { email?: unknown; user?: { email?: unknown } | null };
  return response.user?.email ?? response.email;
}

function isExistingSignupResponse(data: unknown) {
  if (!data || typeof data !== "object") return false;

  const response = data as { session?: unknown; user?: unknown };
  const identities = getSignupResponseIdentities(data);
  if (response.session) return false;
  if (Array.isArray(identities)) return identities.length === 0;

  return !response.user && !getSignupResponseEmail(data);
}

function isExistingAccountMessage(message: string) {
  const normalized = message.toLowerCase();
  return (
    normalized.includes("duplicate") ||
    normalized.includes("already registered") ||
    normalized.includes("already been registered") ||
    normalized.includes("already exists") ||
    normalized.includes("already taken") ||
    normalized.includes("email address is already") ||
    normalized.includes("user already") ||
    (
      normalized.includes("already") &&
      (normalized.includes("email") || normalized.includes("user") || normalized.includes("account")) &&
      (normalized.includes("registered") || normalized.includes("exists") || normalized.includes("taken"))
    )
  );
}

function normalizeAuthReason(message: string) {
  const normalized = message.toLowerCase();
  if (isExistingAccountMessage(message)) return "existing_account";
  if (normalized.includes("password")) return "password";
  if (normalized.includes("email")) return "email";
  return "auth_error";
}
