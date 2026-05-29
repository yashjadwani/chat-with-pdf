import { FormEvent, useState } from "react";
import { ArrowRight, Eye, EyeOff, LockKeyhole, Mail, Shield } from "lucide-react";
import { supabase } from "../../lib/supabase";
import { Button } from "../ui/Button";

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function LoginForm({
  onModeChange,
  onVerificationNeeded
}: {
  onModeChange: () => void;
  onVerificationNeeded: (email: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const emailIsInvalid = email.length > 0 && !emailPattern.test(email.trim());

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    if (!emailPattern.test(email.trim())) {
      setError("Enter a valid email address.");
      setLoading(false);
      return;
    }

    const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
    if (authError) {
      const emailNotConfirmed = authError.message.toLowerCase().includes("email not confirmed");
      const message = emailNotConfirmed ? "Please verify your email before signing in." : authError.message;
      setError(message);
      if (emailNotConfirmed) onVerificationNeeded(email.trim());
    }
    setLoading(false);
  }

  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <div className="form-heading">
        <Shield size={22} />
        <div>
          <h1>Welcome back</h1>
          <p>Open your documents and continue where you left off.</p>
        </div>
      </div>

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
            autoComplete="current-password"
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

      <div className="form-message-slot" aria-live="polite">
        {error ? <p className="form-error">{error}</p> : null}
      </div>

      <Button disabled={loading || emailIsInvalid} type="submit">
        {loading ? "Signing in" : "Sign in"}
        <ArrowRight size={17} />
      </Button>

      <button className="text-button auth-switch-link" type="button" onClick={onModeChange}>
        Create a new account
      </button>
    </form>
  );
}
