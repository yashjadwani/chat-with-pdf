import { FormEvent, useState } from "react";
import { ArrowRight, Mail, Shield } from "lucide-react";
import { supabase } from "../../lib/supabase";
import { Button } from "../ui/Button";

export function LoginForm({ onModeChange }: { onModeChange: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
    if (authError) setError(authError.message);
    setLoading(false);
  }

  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <div className="form-heading">
        <Shield size={22} />
        <div>
          <h1>Welcome back</h1>
          <p>Open your document desk and continue the thread.</p>
        </div>
      </div>

      <label>
        Email
        <span className="input-shell">
          <Mail size={17} />
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
        </span>
      </label>

      <label>
        Password
        <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required />
      </label>

      {error && <p className="form-error">{error}</p>}

      <Button disabled={loading} type="submit">
        {loading ? "Signing in" : "Sign in"}
        <ArrowRight size={17} />
      </Button>

      <button className="text-button" type="button" onClick={onModeChange}>
        Create a new account
      </button>
    </form>
  );
}
