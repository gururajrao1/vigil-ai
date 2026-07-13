/** Mandatory honesty strip for Sources / Discovery hubs. */
export default function SurrogateHonestyBanner() {
  return (
    <aside
      className="va-panel px-4 py-3 text-xs leading-relaxed text-[var(--app-text-muted)]"
      role="note"
    >
      <div className="mono-tag mb-1.5">DATA INTEGRITY · LOCAL SURROGATE SNAPSHOTS</div>
      <p className="m-0">
        Comparative statistical benchmarks and registry-style lookups use{' '}
        <strong className="text-[var(--app-text)] font-medium">local reference surrogates</strong>
        {' '}(openFDA FAERS/MAUDE-style caches and offline KBs). They are not live direct pipes to
        closed global registries such as WHO VigiBase, FDA Sentinel, or NESTcc.
      </p>
    </aside>
  );
}
