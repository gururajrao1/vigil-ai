import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom';
import { api, wakeApi } from '../api';
import { useAuth, useRefresh } from '../App';
import BiotechHomepageRenderer from './BiotechHomepageRenderer';
import { buildFallbackHomepage } from './fallbackLayout';
import { BrandIcon, Spinner } from '@clairlabs-ai/prp-ui';
import { BIOTECH_TOKENS as T } from './tokens';

async function loadHomepage(focusDrug) {
  try {
    return await api.biotechHomepage(focusDrug || undefined);
  } catch {
    const [stats, sigPayload] = await Promise.all([
      api.stats().catch(() => ({})),
      api.signals(focusDrug ? { drug: focusDrug } : {}).catch(() => ({ signals: [] })),
    ]);
    const signals = Array.isArray(sigPayload) ? sigPayload : (sigPayload.signals || []);
    return buildFallbackHomepage({ stats, signals, focusDrug: focusDrug || undefined });
  }
}

function BootLoader({ label = 'Loading VigilAI' }) {
  return (
    <div
      className="flex min-h-[100vh] flex-col items-center justify-center gap-5 text-[var(--cds-sys-text-secondary)]"
      style={{ background: T.canvas, fontFamily: T.fontDisplay }}
    >
      <BrandIcon aria-hidden>VA</BrandIcon>
      <Spinner size="lg" label={label} />
      <div className="text-[13px] tracking-wide">{label}</div>
    </div>
  );
}

/**
 * Public-facing biotech product homepage.
 * Login CTAs stay disabled until the API is awake, then open a real credential form
 * (existing sessions are cleared so Login is never a dashboard bypass).
 */
export default function BiotechHomepagePage() {
  const { tick } = useRefresh();
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const drug = params.get('drug') || '';
  const [layout, setLayout] = useState(null);
  const [err, setErr] = useState(null);
  const [apiReady, setApiReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLayout(buildFallbackHomepage({}));
    setErr(null);
    setApiReady(false);
    wakeApi(90000).then((ok) => {
      if (!cancelled) setApiReady(!!ok);
    });
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

  const goLogin = () => {
    // Force credential entry — never treat Login as a shortcut into the app.
    logout();
    nav('/login', { replace: true });
  };

  const onNavigate = (href) => {
    if (!href) return;
    if (href === '/#manifesto' || href === '/#pillars' || href === '/#spotlight' || href.startsWith('#')) {
      const id = href.includes('#') ? href.split('#')[1] : href.slice(1);
      if (location.pathname !== '/' && location.pathname !== '/home') {
        nav(`/${href.includes('#') ? href.slice(href.indexOf('#')) : `#${id}`}`);
        return;
      }
      document.getElementById(id)?.scrollIntoView({ behavior: 'auto' });
      return;
    }
    if (href === '/login' || href === '/signin') {
      if (!apiReady) return;
      goLogin();
      return;
    }
    // Platform routes require a verified session — guests always hit Login.
    if (!user) {
      if (!apiReady) return;
      goLogin();
      return;
    }
    nav(href);
  };

  const onAction = async (action) => {
    if (!user) {
      if (!apiReady) return;
      goLogin();
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

  if (err && !layout) {
    return (
      <div style={{ background: T.canvas, color: T.muted, minHeight: '100vh', padding: 48, fontFamily: T.fontMono }}>
        Homepage unavailable · {err}
      </div>
    );
  }
  if (!layout) {
    return <BootLoader />;
  }

  const loginLabel = apiReady ? 'Login' : 'Connecting…';
  const loginHref = '/login';

  const navLayout = {
    ...layout,
    navigation: {
      ...layout.navigation,
      items: [
        ...(layout.navigation?.items || []).filter((i) => i.id !== 'platform' && i.id !== 'signin'),
        {
          id: 'signin',
          label: loginLabel,
          href: loginHref,
          emphasis: true,
          disabled: !apiReady,
        },
      ],
    },
    hero_manifesto: {
      ...layout.hero_manifesto,
      primary_cta: { label: loginLabel, href: loginHref, disabled: !apiReady },
      secondary_cta: undefined,
    },
    cta_strip: user
      ? (layout.cta_strip || {})
      : {
          ...(layout.cta_strip || {}),
          title: layout.cta_strip?.title || 'Ready when you are',
          body: 'Sign in with your VigilAI account to open the pharmacovigilance workbench.',
          buttons: [],
        },
    // Hide mutating homepage actions until signed in as analyst+.
    actions: user ? (layout.actions || []) : [],
  };

  return (
    <BiotechHomepageRenderer
      layout={navLayout}
      onNavigate={onNavigate}
      onAction={onAction}
    />
  );
}
