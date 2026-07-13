import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../App';
import { Button } from '../components/ui';

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('admin@vigilai.dev');
  const [password, setPassword] = useState('admin123');
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr('');
    try {
      const res = mode === 'login'
        ? await api.login(email, password)
        : await api.register(email, password, name);
      login(res.token, res.user);
      nav('/dashboard', { replace: true });
    } catch (e2) {
      const msg = String(e2?.message || e2 || 'Failed');
      setErr(
        /failed to fetch|network|timeout|abort/i.test(msg)
          ? 'Server is waking up or unreachable. Wait ~30s and try again.'
          : msg
      );
    }
    setBusy(false);
  };

  return (
    <div className="login-gate min-h-[100dvh] w-full flex items-center justify-center px-4 py-10">
      <div
        className="login-gate-panel w-full max-w-md border border-[var(--app-border)] bg-[var(--app-surface-solid)] p-6 sm:p-8"
        style={{ borderRadius: 4 }}
      >
        <div className="mb-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[var(--app-accent)] mb-2 font-mono">VigilAI</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[var(--app-text)] leading-tight" style={{ letterSpacing: '-0.04em' }}>
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </h1>
          <p className="mt-2 text-sm text-[var(--app-text-muted)] leading-snug">
            Worldwide pharmacovigilance & device-vigilance — social listening to explainable safety signals.
          </p>
        </div>

        <form onSubmit={submit} className="space-y-3">
          {mode === 'register' && (
            <input
              className="app-input"
              placeholder="Full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="name"
            />
          )}
          <input
            className="app-input"
            placeholder="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
          />
          <input
            type="password"
            className="app-input"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
          />
          {err && <div className="text-xs text-rose-400 font-mono">{err}</div>}
          <Button type="submit" variant="primary" disabled={busy} className="w-full">
            {busy ? 'Please wait…' : (mode === 'login' ? 'Enter VigilAI' : 'Register')}
          </Button>
        </form>

        <p className="mt-4 text-[11px] text-[var(--app-text-faint)] leading-snug font-mono">
          Demo: <span className="text-[var(--app-text-muted)]">admin@vigilai.dev</span> /{' '}
          <span className="text-[var(--app-text-muted)]">admin123</span>
        </p>

        <button
          type="button"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          className="mt-4 text-xs text-[var(--app-accent)]"
        >
          {mode === 'login' ? 'Need an account? Register' : 'Have an account? Sign in'}
        </button>

        <div className="mt-6">
          <Link to="/" className="text-xs text-[var(--app-text-muted)] font-mono">
            ← Back to homepage
          </Link>
        </div>
      </div>
    </div>
  );
}
