import { FormEvent, useState } from "react";
import { ArrowRight, Eye, EyeOff, LockKeyhole, Mail, Sparkles, UserRound } from "lucide-react";
import { supabase } from "../../lib/supabase";
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
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const emailIsInvalid = email.length > 0 && !emailPattern.test(email.trim());
  const passwordsDoNotMatch = confirmPassword.length > 0 && password !== confirmPassword;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setSuccess(false);

    if (!emailPattern.test(email.trim())) {
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
      email,
      password,
      options: {
        data: {
          display_name: displayName.trim()
        }
      }
    });
    if (error) {
      setMessage(error.message);
      setSuccess(false);
    } else {
      if (data.session) await supabase.auth.signOut();
      setSuccess(true);
      onVerificationNeeded(email.trim());
    }
    setLoading(false);
  }

  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <div className="form-heading">
        <Sparkles size={22} />
        <div>
          <h1>Create account</h1>
          <p>Start a private place for your documents and questions.</p>
        </div>
      </div>

      <label>
        Name
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
      <label>
        Email
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

      <label>
        Password
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

      <label>
        Confirm password
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

      {message && <p className={success ? "form-note form-success" : "form-error"}>{message}</p>}

      <Button disabled={loading || emailIsInvalid || passwordsDoNotMatch} type="submit">
        {loading ? "Creating" : "Create account"}
        <ArrowRight size={17} />
      </Button>

      <button className="text-button" type="button" onClick={onModeChange}>
        Already have an account?
      </button>
    </form>
  );
}
