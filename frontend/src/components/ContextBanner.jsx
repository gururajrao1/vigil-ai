import { useEffect, useState } from 'react';
import { Button, Card } from './ui';

const STORAGE_KEY = 'vigilai_context_banner_dismissed_v1';

const STEPS = [
  {
    id: 'what',
    title: 'What is signal detection?',
    body: (
      <>
        In pharmacovigilance, a <em>safety signal</em> is information that suggests a new
        causal association — or a new aspect of a known association — between a product
        and an adverse event. VigilAI watches unstructured patient voice (forums, Reddit, X)
        in near real time and scores product–event pairs with the same disproportionality
        family used in spontaneous-reporting systems: PRR, ROR, IC₀₂₅, and EBGM.
      </>
    ),
  },
  {
    id: 'who',
    title: 'Who is this for?',
    body: (
      <>
        Built for PV scientists, medical reviewers, safety physicians, and device-vigilance
        teams who need an early <em>prepared mind</em> on emerging risk — not a replacement
        for FAERS/MAUDE, VigiBase, or clinical adjudication. Domain experts can inspect
        severity badges for the exact statistical parameters behind each tier.
      </>
    ),
  },
  {
    id: 'why',
    title: 'Why post-velocity matters',
    body: (
      <>
        Public registries lag weeks to months behind patient experience. Checking
        post-velocity anomalies (spikes, strengthening PRR/IC₀₂₅, critical severity)
        compresses time-to-awareness for rare or late adverse events — the gap Trontell
        and Downing highlighted for novel therapeutics and Class III devices — so review
        queues can prioritize before traditional case series accumulate.
      </>
    ),
  },
  {
    id: 'how',
    title: 'How to read this workspace',
    body: (
      <>
        Start with corpus metrics below, then open the Signal workbench. Hover or click any
        severity badge (Critical / High / Medium / Low) to open the parameter audit:
        PRR, ROR, IC₀₂₅, EBGM versus corporate thresholds, plus an explicit note that
        comorbidities in consumer text remain unverified.
      </>
    ),
  },
];

/**
 * 3–4 minute introductory context banner for the main dashboard.
 * Dismissible; preference stored in localStorage.
 */
export default function ContextBanner() {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  });
  const [step, setStep] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (dismissed) return undefined;
    const t = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(t);
  }, [dismissed]);

  if (dismissed) return null;

  const current = STEPS[step];
  const isLast = step >= STEPS.length - 1;

  const dismiss = () => {
    try {
      localStorage.setItem(STORAGE_KEY, '1');
    } catch { /* ignore */ }
    setVisible(false);
    setTimeout(() => setDismissed(true), 280);
  };

  return (
    <Card
      className={`overflow-hidden border-[var(--app-border-accent)] transition-all duration-300 ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1'
      }`}
    >
      <div className="px-4 pt-3 pb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--app-accent)]">
            VigilAI · context
          </div>
          <h2 className="text-sm font-semibold text-[var(--app-text)] mt-0.5">
            Before the charts — why these metrics exist
          </h2>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="text-[var(--app-text-faint)] hover:text-[var(--app-text-muted)] text-xs"
          aria-label="Dismiss context banner"
        >
          Dismiss
        </button>
      </div>

      <div className="px-4 flex gap-1.5 mb-3">
        {STEPS.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setStep(i)}
            className={`h-1 flex-1 rounded-full transition-colors ${
              i === step ? 'bg-[var(--app-accent)]' : i < step ? 'bg-teal-700/50' : 'bg-[var(--app-border)]'
            }`}
            aria-label={`Step ${i + 1}: ${s.title}`}
          />
        ))}
      </div>

      <div className="px-4 pb-4 min-h-[7.5rem]">
        <div className="text-xs font-medium text-[var(--app-text-secondary)] mb-1.5">
          {step + 1}/{STEPS.length} · {current.title}
        </div>
        <p className="text-sm text-[var(--app-text-muted)] leading-relaxed max-w-3xl">
          {current.body}
        </p>
        <div className="mt-4 flex items-center gap-2">
          <Button
            variant="ghost"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            Back
          </Button>
          {!isLast ? (
            <Button onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}>
              Next
            </Button>
          ) : (
            <Button onClick={dismiss}>Enter dashboard</Button>
          )}
          <span className="text-[10px] text-[var(--app-text-faint)] ml-auto">
            ~3–4 min read · skip anytime
          </span>
        </div>
      </div>
    </Card>
  );
}
