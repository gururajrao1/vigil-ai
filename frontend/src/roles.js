/** Role helpers — admin (3) > analyst (2) > viewer (1). */
const RANK = { admin: 3, analyst: 2, viewer: 1 };

export function roleRank(role) {
  return RANK[(role || '').toLowerCase()] || 0;
}

export function hasMinRole(user, minRole) {
  return roleRank(user?.role) >= roleRank(minRole);
}

export function isAdmin(user) {
  return hasMinRole(user, 'admin');
}

export function isAnalyst(user) {
  return hasMinRole(user, 'analyst');
}

/** Viewer: browse only. Analyst+: ingest / triage / forge. Admin: users + reset. */
export const ROLE_GUIDE = [
  {
    role: 'viewer',
    label: 'Viewer',
    summary: 'Read-only access to dashboards, signals, evidence, and alerts.',
  },
  {
    role: 'analyst',
    label: 'Analyst',
    summary: 'All viewer access plus ingest, demo corpus, Forge, reviews, and project ops.',
  },
  {
    role: 'admin',
    label: 'Admin',
    summary: 'All analyst access plus user management and full database reset.',
  },
];
