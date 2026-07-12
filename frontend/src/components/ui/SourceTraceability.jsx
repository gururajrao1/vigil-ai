/**
 * Source-traceability narrative highlighter.
 *
 * Cleans scrape-broken spacing, then highlights entities with word-boundary
 * RegExp matches so short prefixes ("flu") never steal a longer clinical token
 * ("fluoroquinolone" / "fluoroquinolones").
 */
import { useMemo } from 'react';

/** Known long compounds that scrapers commonly fracture with whitespace. */
const STITCH_COMPOUNDS = [
  'fluoroquinolones', 'fluoroquinolone',
  'levofloxacin', 'ciprofloxacin', 'moxifloxacin', 'ofloxacin',
  'acetaminophen', 'paracetamol', 'isotretinoin', 'accutane',
  'atorvastatin', 'simvastatin', 'rosuvastatin', 'metformin',
  'sertraline', 'fluoxetine', 'paroxetine', 'escitalopram',
  'semaglutide', 'pembrolizumab', 'nivolumab', 'adalimumab',
  'rhabdomyolysis', 'anaphylaxis', 'myocarditis', 'pericarditis',
  'thrombocytopenia', 'neutropenia', 'pancytopenia',
  'stevensjohnson',
];

/** Overarching drug-class / family labels (vs specific active products). */
const DRUG_CLASS_TERMS = new Set([
  'fluoroquinolone', 'fluoroquinolones',
  'quinolone', 'quinolones',
  'statin', 'statins',
  'ssri', 'ssris',
  'nsaid', 'nsaids',
  'beta blocker', 'beta-blocker', 'beta blockers',
  'ace inhibitor', 'ace inhibitors',
  'arb', 'arbs',
  'ppi', 'ppis',
  'benzodiazepine', 'benzodiazepines',
  'opioid', 'opioids',
  'corticosteroid', 'corticosteroids',
  'aminoglycoside', 'aminoglycosides',
  'macrolide', 'macrolides',
  'tetracycline', 'tetracyclines',
  'chemotherapy', 'vaccines', 'vaccine',
]);

const INVISIBLE_RE = /[\u00ad\u200b\u200c\u200d\ufeff]/g;
const HTML_TAG_RE = /<[^>]+>/g;
const MULTI_WS_RE = /\s+/g;

function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Build a regex that allows optional whitespace between every character. */
function compoundPattern(compound) {
  const body = compound.split('').map(escapeRegExp).join('\\s*');
  return new RegExp(`(?<![A-Za-z0-9])${body}(?![A-Za-z0-9])`, 'gi');
}

const _STITCH_PATTERNS = STITCH_COMPOUNDS
  .slice()
  .sort((a, b) => b.length - a.length)
  .map((c) => ({ re: compoundPattern(c), canon: c }));

/**
 * Collapse whitespace, strip invisible/HTML debris, stitch known compounds.
 */
export function cleanScrapedText(raw) {
  if (!raw) return '';
  let text = String(raw).replace(INVISIBLE_RE, '').replace(HTML_TAG_RE, ' ');
  text = text.replace(MULTI_WS_RE, ' ').trim();
  for (const { re, canon } of _STITCH_PATTERNS) {
    re.lastIndex = 0;
    text = text.replace(re, (match) => {
      if (match === match.toUpperCase()) return canon.toUpperCase();
      if (match[0] && match[0] === match[0].toUpperCase()) {
        return canon.charAt(0).toUpperCase() + canon.slice(1);
      }
      return canon;
    });
  }
  return text.replace(MULTI_WS_RE, ' ').trim();
}

function candidateSurfaces(entity) {
  const out = [];
  const push = (v) => {
    const s = (v || '').trim();
    if (!s || s.length < 2) return;
    if (!out.includes(s)) out.push(s);
  };
  push(entity.normalized);
  push(entity.pt);
  push(entity.generic);
  push(entity.text);
  push(entity.phrase);
  if (entity.text) push(cleanScrapedText(entity.text));
  // Longest first — never let "flu" claim "fluoroquinolone"
  return out.sort((a, b) => b.length - a.length);
}

/**
 * Word-boundary match for a surface, allowing common plural suffixes
 * (fluoroquinolone ↔ fluoroquinolones) without matching bare prefixes.
 */
export function findBoundedMatch(haystack, needle, fromIndex = 0) {
  if (!haystack || !needle || needle.length < 2) return null;
  const region = fromIndex > 0 ? haystack.slice(fromIndex) : haystack;
  if (!region) return null;

  // Multi-word surfaces: boundaries on first/last token edges
  const parts = needle.trim().split(/\s+/).map(escapeRegExp);
  const core = parts.join('\\s+');
  // Optional plural / possessive: s | es | 's
  const pattern = new RegExp(`\\b(${core})(?:es|s)?\\b`, 'gi');
  pattern.lastIndex = 0;
  const m = pattern.exec(region);
  if (!m) return null;
  const start = fromIndex + m.index;
  const end = start + m[0].length;
  return { start, end, matched: m[0] };
}

function isDrugClassTerm(entity, display) {
  const labels = [
    display,
    entity.normalized,
    entity.text,
    entity.generic,
    entity.pt,
  ].map((v) => (v || '').toLowerCase().trim());
  if (entity.entity_role === 'class' || entity.kind === 'class' || entity.is_class) {
    return true;
  }
  return labels.some((l) => DRUG_CLASS_TERMS.has(l));
}

/**
 * Re-map entity spans onto cleanedText with boundary-safe RegExp placement.
 */
export function remapEntitySpans(cleanedText, entities = {}) {
  if (!cleanedText) return [];

  const spans = [];
  const occupied = [];

  const overlaps = (a, b) => a.start < b.end && b.start < a.end;
  const claim = (start, end) => {
    const span = { start, end };
    if (occupied.some((o) => overlaps(o, span))) return false;
    occupied.push(span);
    return true;
  };

  const tryPlace = (surface) => {
    let from = 0;
    while (from < cleanedText.length) {
      const hit = findBoundedMatch(cleanedText, surface, from);
      if (!hit) return null;
      if (claim(hit.start, hit.end)) return hit;
      from = hit.start + 1;
    }
    return null;
  };

  // Process drug entities before symptoms so class/product marks win overlapping claims
  const buckets = [
    ['drugs', entities.drugs || []],
    ['symptoms', entities.symptoms || []],
    ['conditions', entities.conditions || []],
  ];

  // Within each bucket, longer surfaces first (via candidateSurfaces sort)
  buckets.forEach(([type, list]) => {
    const ranked = [...list].sort((a, b) => {
      const la = (a.normalized || a.text || a.pt || '').length;
      const lb = (b.normalized || b.text || b.pt || '').length;
      return lb - la;
    });
    ranked.forEach((e) => {
      let placed = null;
      let usedSurface = '';
      for (const surface of candidateSurfaces(e)) {
        placed = tryPlace(surface);
        if (placed) {
          usedSurface = surface;
          break;
        }
      }
      if (!placed) return;
      const display = cleanedText.slice(placed.start, placed.end);
      spans.push({
        ...e,
        type,
        start: placed.start,
        end: placed.end,
        display,
        matchSurface: usedSurface,
        semanticRole: type === 'drugs'
          ? (isDrugClassTerm(e, display) ? 'drug_class' : 'drug_product')
          : type,
      });
    });
  });

  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  return spans;
}

const COLORS = {
  drug_class: 'bg-violet-500/30 text-violet-100 ring-1 ring-violet-400/40 font-medium',
  drug_product: 'bg-sky-500/25 text-sky-200 ring-1 ring-sky-400/30',
  drugs: 'bg-sky-500/25 text-sky-200',
  symptoms: 'bg-rose-500/25 text-rose-200',
  conditions: 'bg-amber-500/25 text-amber-200',
};

function markClassFor(span) {
  if (span.semanticRole === 'drug_class') return COLORS.drug_class;
  if (span.semanticRole === 'drug_product') return COLORS.drug_product;
  return COLORS[span.type] || '';
}

/**
 * Highlight clinical entities in a source narrative with boundary-safe matches.
 */
export default function SourceTraceability({ text, entities, className = '' }) {
  const { cleaned, nodes } = useMemo(() => {
    const cleanedText = cleanScrapedText(text || '');
    if (!cleanedText) return { cleaned: '', nodes: null };

    const spans = remapEntitySpans(cleanedText, entities || {});
    const out = [];
    let cursor = 0;

    spans.forEach((s, i) => {
      if (s.start < cursor) return;
      if (s.start > cursor) {
        out.push(<span key={`t${i}`}>{cleanedText.slice(cursor, s.start)}</span>);
      }
      const isVern = s.type === 'symptoms' && s.source === 'vernacular';
      const roleLabel = s.semanticRole === 'drug_class'
        ? 'drug class'
        : s.semanticRole === 'drug_product'
          ? 'active product'
          : (s.pt || s.normalized || s.display);
      out.push(
        <mark
          key={`m${i}`}
          title={isVern ? `patient phrasing → ${s.pt || s.normalized}` : roleLabel}
          data-entity-type={s.type}
          data-semantic-role={s.semanticRole}
          className={`rounded px-1 ${markClassFor(s)} ${isVern ? 'underline decoration-dotted decoration-rose-300/70' : ''}`}
        >
          {cleanedText.slice(s.start, s.end)}
          {isVern && (
            <sup className="ml-0.5 text-[9px] text-rose-300/90" title={`mapped to MedDRA PT: ${s.pt || s.normalized}`}>
              →{s.pt || s.normalized}
            </sup>
          )}
        </mark>,
      );
      cursor = s.end;
    });

    if (cursor < cleanedText.length) {
      out.push(<span key="tail">{cleanedText.slice(cursor)}</span>);
    }
    return { cleaned: cleanedText, nodes: out };
  }, [text, entities]);

  if (!cleaned) return text ? <span className={className}>{text}</span> : null;
  return <span className={className}>{nodes}</span>;
}
