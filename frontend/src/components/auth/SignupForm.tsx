import { FormEvent, useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { supabase } from "../../lib/supabase";
import { Button } from "../ui/Button";

export function SignupForm({ onModeChange }: { onModeChange: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage("");

    const { error } = await supabase.auth.signUp({ email, password });
    setMessage(error ? error.message : "Account created. Check your email if confirmation is enabled.");
    setLoading(false);
  }

  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <div className="form-heading">
        <Sparkles size={22} />
        <div>
          <h1>Create account</h1>
          <p>Start a private library for cited document answers.</p>
        </div>
      </div>

      <label>
        Email
        <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
      </label>

      <label>
        Password
        <input
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          type="password"
          minLength={6}
          required
        />
      </label>

      {message && <p className="form-note">{message}</p>}

      <Button disabled={loading} type="submit">
        {loading ? "Creating" : "Create account"}
        <ArrowRight size={17} />
      </Button>

      <button className="text-button" type="button" onClick={onModeChange}>
        Already have an account?
      </button>
    </form>
  );
}
