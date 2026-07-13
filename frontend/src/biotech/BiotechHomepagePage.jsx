import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom';
import { api } from '../api';
import { useAuth, useRefresh } from '../App';
import BiotechHomepageRenderer from './BiotechHomepageRenderer';
import { buildFallbackHomepage } from './fallbackLayout';
import { BIOTECH_TOKENS as T } from './tokens';

async function loadHomepage(focusDrug) {
  try {
    return await api.biotechHomepage(focusDrug || undefined);
  } catch {
    // Render may lag behind Vercel — compose from endpoints that already exist in production.
    const [stats, sigPayload] = await Promise.all([
      api.stats().catch(() => ({})),
      api.signals(focusDrug ? { drug: focusDrug } : {}).catch(() => ({ signals: [] })),
    ]);
    const signals = Array.isArray(sigPayload) ? sigPayload : (sigPayload.signals || []);
    return buildFallbackHomepage({ stats, signals, focusDrug: focusDrug || undefined });
  }
}

/**
 * Public-facing biotech product homepage.
 * Prefers FastMCP/HTTP schema; falls back to stats+signals if API host is stale.
 */
export default function BiotechHomepagePage() {
  const { tick } = useRefresh();
  const { user } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const drug = params.get('drug') || '';
  const [layout, setLayout] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLayout(null);
    loadHomepage(drug)
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
    // Hash anchors on the homepage (mission / pillars / spotlight)
    if (href === '/#manifesto' || href === '/#pillars' || href === '/#spotlight' || href.startsWith('#')) {
      const id = href.includes('#') ? href.split('#')[1] : href.slice(1);
      if (location.pathname !== '/' && location.pathname !== '/home') {
        nav(`/${href.includes('#') ? href.slice(href.indexOf('#')) : `#${id}`}`);
        return;
      }
      document.getElementById(id)?.scrollIntoView({ behavior: 'auto' });
      return;
    }
    if (!user && href !== '/login' && href !== '/' && href !== '/home') {
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
      setLayout(await loadHomepage(drug));
      return;
    }
    if (action?.kind === 'forge_sim') {
      await api.streamTick(action.payload?.n || 5, true);
      setLayout(await loadHomepage(drug));
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
