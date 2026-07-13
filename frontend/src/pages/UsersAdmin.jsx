import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../App';
import { isAdmin, ROLE_GUIDE } from '../roles';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

const ROLES = ['viewer', 'analyst', 'admin'];

export default function UsersAdmin() {
  const { user } = useAuth();
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [form, setForm] = useState({
    email: '',
    password: '',
    full_name: '',
    role: 'analyst',
  });

  const load = async () => {
    setBusy(true);
    setErr('');
    try {
      const res = await api.users();
      setRows(res.users || []);
    } catch (e) {
      setErr(e.message || String(e));
    }
    setBusy(false);
  };

  useEffect(() => {
    if (isAdmin(user)) load();
  }, [user]);

  if (!isAdmin(user)) {
    return <Navigate to="/dashboard" replace />;
  }

  const create = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr('');
    try {
      await api.createUser(form);
      setForm({ email: '', password: '', full_name: '', role: 'analyst' });
      await load();
    } catch (ex) {
      setErr(ex.message || String(ex));
      setBusy(false);
    }
  };

  const changeRole = async (id, role) => {
    setErr('');
    try {
      await api.setUserRole(id, role);
      await load();
    } catch (ex) {
      setErr(ex.message || String(ex));
    }
  };

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <CardHeader
          title="User administration"
          subtitle="Admin-only · list accounts, create users, and assign roles (admin › analyst › viewer)."
        />
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {ROLE_GUIDE.map((r) => (
            <div
              key={r.role}
              className="border border-[var(--app-border)] bg-[var(--app-surface)] p-3"
              style={{ borderRadius: 4 }}
            >
              <div className="text-xs font-semibold uppercase tracking-wide text-[var(--app-accent)] font-mono">
                {r.label}
              </div>
              <p className="mt-1 text-xs text-[var(--app-text-muted)] leading-snug">{r.summary}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-5">
        <CardHeader title="Create user" subtitle="New accounts can sign in immediately with the password you set." />
        <form onSubmit={create} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <input
            className="app-input lg:col-span-1"
            placeholder="Email"
            type="email"
            required
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
          <input
            className="app-input"
            placeholder="Password"
            type="password"
            required
            minLength={6}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          <input
            className="app-input"
            placeholder="Full name"
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          />
          <select
            className="app-input"
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Saving…' : 'Create'}
          </Button>
        </form>
        {err && <div className="mt-3 text-xs text-rose-400 font-mono">{err}</div>}
      </Card>

      <Card className="p-5">
        <CardHeader title="Accounts" subtitle={`${rows.length} user(s)`} right={
          <Button variant="ghost" disabled={busy} onClick={load}>Refresh</Button>
        } />
        {busy && !rows.length ? (
          <Spinner label="Loading users…" />
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-[var(--app-text-faint)] font-mono border-b border-[var(--app-border)]">
                  <th className="py-2 pr-3">ID</th>
                  <th className="py-2 pr-3">Email</th>
                  <th className="py-2 pr-3">Name</th>
                  <th className="py-2 pr-3">Role</th>
                  <th className="py-2 pr-3">Active</th>
                  <th className="py-2">Last login</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.id} className="border-b border-[var(--app-border)]/60">
                    <td className="py-2.5 pr-3 font-mono text-xs text-[var(--app-text-muted)]">{u.id}</td>
                    <td className="py-2.5 pr-3 text-[var(--app-text)]">{u.email}</td>
                    <td className="py-2.5 pr-3 text-[var(--app-text-muted)]">{u.full_name || '—'}</td>
                    <td className="py-2.5 pr-3">
                      <select
                        className="app-input text-xs py-1"
                        value={u.role}
                        disabled={u.id === user?.id}
                        title={u.id === user?.id ? 'Cannot change your own role here' : 'Change role'}
                        onChange={(e) => changeRole(u.id, e.target.value)}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2.5 pr-3">
                      <Badge
                        value={u.is_active ? 'active' : 'off'}
                        className={u.is_active
                          ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                          : 'bg-slate-700/40 text-slate-400 border-slate-600/40'}
                      />
                    </td>
                    <td className="py-2.5 text-xs text-[var(--app-text-faint)] font-mono">
                      {u.last_login ? new Date(u.last_login).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
