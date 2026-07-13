import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useAuth, useRefresh } from '../App';
import BiotechHomepageRenderer from './BiotechHomepageRenderer';
import { BIOTECH_TOKENS as T } from './tokens';

/**
 * Public-facing biotech product homepage.
 * Schema from FastMCP / HTTP bridge — optional ?drug= scopes the spotlight.
 */
export default function BiotechHomepagePage() {
  const { tick } = useRefresh();
  const { user } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const drug = params.get('drug') || '';
  const [layout, setLayout] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .biotechHomepage(drug || undefined)
      .then((d) => {
        if (!cancelled) {
          setLayout(d);
          setErr(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(e.message || String(e));
      });
    return () => { cancelled = true; };
  }, [drug, tick]);

  const onNavigate = (href) => {
    if (!href) return;
    if (href.startsWith('/#')) {
      const id = href.slice(2);
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
      return;
    }
    if (href.startsWith('#')) {
      document.getElementById(href.slice(1))?.scrollIntoView({ behavior: 'smooth' });
      return;
    }
    if (!user && (href.startsWith('/dashboard') || href.startsWith('/signals') || href.startsWith('/lenses'))) {
      nav('/login');
      return;
    }
    nav(href);
  };

  const onAction = async (action) => {
    if (!user) {
      nav('/login');
      return;
    }
    if (action?.kind === 'recompute') {
      await api.recompute();
      setLayout(await api.biotechHomepage(drug || undefined));
      return;
    }
    if (action?.kind === 'forge_sim') {
      await api.streamTick(action.payload?.n || 5, true);
      setLayout(await api.biotechHomepage(drug || undefined));
    }
  };

  if (err) {
    return (
      <div style={{ background: T.canvas, color: T.muted, minHeight: '100vh', padding: 48, fontFamily: T.fontMono }}>
        homepage schema unavailable · {err}
      </div>
    );
  }
  if (!layout) {
    return (
      <div style={{ background: T.canvas, color: T.muted, minHeight: '100vh', padding: 48, fontFamily: T.fontMono }}>
        composing biotech canvas…
      </div>
    );
  }

  // Inject sign-in CTA into nav when logged out
  const navLayout = !user
    ? {
        ...layout,
        navigation: {
          ...layout.navigation,
          items: [
            ...(layout.navigation?.items || []).filter((i) => i.id !== 'platform'),
            { id: 'signin', label: 'Sign in', href: '/login', emphasis: true },
          ],
        },
        hero_manifesto: {
          ...layout.hero_manifesto,
          primary_cta: { label: 'Sign in to enter', href: '/login' },
          secondary_cta: layout.hero_manifesto?.secondary_cta,
        },
      }
    : layout;

  return (
    <BiotechHomepageRenderer
      layout={navLayout}
      onNavigate={onNavigate}
      onAction={onAction}
    />
  );
}
