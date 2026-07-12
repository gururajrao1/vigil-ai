import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../App';
import { Button, Card } from '../components/ui';

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
    setBusy(true); setErr('');
    try {
      const res = mode === 'login'
        ? await api.login(email, password)
        : await api.register(email, password, name);
      login(res.token, res.user);
      nav('/');
    } catch (e2) {
      const msg = String(e2?.message || e2 || 'Failed');
      setErr(
        /failed to fetch|network|timeout|abort/i.test(msg)
          ? 'Server unreachable or busy (ingest may be locking the DB). Wait a few seconds and retry — use a single backend on port 8010.'
          : msg
      );
    }
    setBusy(false);
  };

  return (
    <div className="max-w-md mx-auto mt-10">
      <Card className="p-6">
        <h2 className="text-xl font-bold text-slate-100 mb-1">
          {mode === 'login' ? 'Sign in to VigilAI' : 'Create an account'}
        </h2>
        <p className="text-xs text-slate-500 mb-4">
          Seeded admin: <span className="text-slate-300">admin@vigilai.dev / admin123</span>
        </p>
        <form onSubmit={submit} className="space-y-3">
          {mode === 'register' && (
            <input className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100"
                   placeholder="Full name" value={name} onChange={(e) => setName(e.target.value)} />
          )}
          <input className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100"
                 placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input type="password" className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100"
                 placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {err && <div className="text-xs text-rose-400">{err}</div>}
          <Button variant="primary" disabled={busy} className="w-full">
            {busy ? 'Please wait…' : (mode === 'login' ? 'Sign in' : 'Register')}
          </Button>
        </form>
        <button onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
                className="mt-4 text-xs text-sky-400 hover:underline">
          {mode === 'login' ? 'Need an account? Register' : 'Have an account? Sign in'}
        </button>
      </Card>
    </div>
  );
}
