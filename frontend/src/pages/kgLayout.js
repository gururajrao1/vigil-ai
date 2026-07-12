/** Layered KG layout + node inspection helpers. */

export const TYPE_META = {
  drug: {
    label: 'Drug',
    color: '#38bdf8',
    description:
      'Monitored pharmaceutical product (generic/INN). Hubs link to reported adverse events and comorbidity context from social-listening signals.',
    edgeRole: 'Source product in disproportionality (drug → AE) paths.',
  },
  symptom: {
    label: 'Adverse event / symptom',
    color: '#f43f5e',
    description:
      'MedDRA-style Preferred Term (PT) — patient-reported symptom or adverse event aggregated across posts.',
    edgeRole: 'Outcome node in PRR/ROR signal detection; may connect to geographic clusters.',
  },
  condition: {
    label: 'Condition / indication',
    color: '#f59e0b',
    description:
      'Comorbidity or therapeutic indication mentioned alongside the drug in patient narratives.',
    edgeRole: 'Contextual link (drug ↔ condition) — not a causality assertion.',
  },
  region: {
    label: 'Geographic region',
    color: '#94a3b8',
    description:
      'Country or region where supporting patient reports originated (from ingested post metadata).',
    edgeRole: 'Spatial clustering — symptom → region edges show where an AE is being discussed.',
  },
  protein: {
    label: 'Protein / CYP target',
    color: '#14b8a6',
    description:
      'STITCH/STRING human (species=9606) binding partner with confidence ≥ 0.700 — filters co-prescription noise.',
    edgeRole: 'Molecular plausibility gate (drug → binds → protein).',
  },
};

export const EDGE_META = {
  adverse: {
    label: 'Adverse signal',
    desc: 'Drug → symptom disproportionality edge (PRR / strength from signal engine).',
  },
  indication: {
    label: 'Indication',
    desc: 'Drug linked to condition as treatment context.',
  },
  condition: {
    label: 'Comorbidity',
    desc: 'Drug associated with co-occurring condition in reports.',
  },
  region: {
    label: 'Geographic',
    desc: 'Symptom discussed in this region.',
  },
  binds: {
    label: 'STITCH binding',
    desc: 'Drug–protein / CYP interaction (confidence ≥ 0.70).',
  },
};

/** Column positions (0–1) for type-layered layout. */
const COL_X = {
  drug: 0.08,
  protein: 0.26,
  condition: 0.44,
  symptom: 0.64,
  region: 0.88,
};

const TYPE_ORDER = ['drug', 'protein', 'condition', 'symptom', 'region'];

export function columnX(type, width) {
  return (COL_X[type] ?? 0.5) * width;
}

/** Assign initial Y spread per column; returns nodes with x/y hints.

  Dense columns get staggered X offsets and guaranteed min vertical gap so
  labels don't stack on top of each other.
*/
export function seedLayeredPositions(nodes, width, height) {
  const padding = 52;
  const groups = {
    drug: [],
    protein: [],
    condition: [],
    symptom: [],
    region: [],
  };
  nodes.forEach((n) => {
    const t = groups[n.type] ? n.type : 'symptom';
    groups[t].push(n);
  });

  TYPE_ORDER.forEach((t) => {
    groups[t].sort((a, b) => (b.degree || 0) - (a.degree || 0) || String(a.label || '').localeCompare(String(b.label || '')));
  });

  const maxCol = Math.max(1, ...TYPE_ORDER.map((t) => groups[t].length));
  // Prefer taller canvas when a column is crowded
  const minGap = maxCol > 24 ? 18 : maxCol > 14 ? 22 : 28;
  const needed = padding * 2 + (maxCol - 1) * minGap;
  const usableH = Math.max(height, needed);
  const spread = Math.max(usableH - padding * 2, 80);
  const colW = width / 5;
  const stagger = Math.min(14, colW * 0.12);

  return nodes.map((n) => {
    const t = groups[n.type] ? n.type : 'symptom';
    const list = groups[t];
    const idx = list.findIndex((x) => x.id === n.id);
    const baseX = columnX(t, width);
    // Zig-zag within column to reduce label collisions
    const x = baseX + ((idx % 2 === 0) ? -stagger : stagger);
    const y =
      padding + (list.length <= 1 ? spread / 2 : (idx / (list.length - 1)) * spread);
    return {
      ...n,
      __colX: x,
      __seedY: y,
      __colType: t,
      __colIndex: idx,
      __colSize: list.length,
      __labelSide: idx % 2 === 0 ? 'left' : 'right',
    };
  });
}

/** Suggested canvas height for readable vertical spacing. */
export function suggestedGraphHeight(nodes, minH = 560, maxH = 1100) {
  const counts = {};
  (nodes || []).forEach((n) => {
    const t = n.type || 'symptom';
    counts[t] = (counts[t] || 0) + 1;
  });
  const maxCol = Math.max(1, ...Object.values(counts), 1);
  const gap = maxCol > 24 ? 18 : maxCol > 14 ? 22 : 28;
  return Math.min(maxH, Math.max(minH, 80 + maxCol * gap));
}

/**
 * Keep the most connected nodes per column when the graph is dense.
 * Always keeps selected/focus ids if provided.
 */
export function densifyGraph(kg, { maxPerColumn = 14, keepIds = [] } = {}) {
  if (!kg?.nodes?.length) return kg;
  const keep = new Set(keepIds.filter(Boolean));
  const byType = {};
  kg.nodes.forEach((n) => {
    const t = n.type || 'symptom';
    (byType[t] = byType[t] || []).push(n);
  });

  const allowed = new Set(keep);
  Object.values(byType).forEach((list) => {
    const ranked = [...list].sort((a, b) => (b.degree || 0) - (a.degree || 0));
    ranked.slice(0, maxPerColumn).forEach((n) => allowed.add(n.id));
  });

  // Pull in 1-hop neighbors of kept hubs so paths don't look orphaned
  (kg.edges || []).forEach((e) => {
    const s = typeof e.source === 'object' ? e.source.id : e.source;
    const t = typeof e.target === 'object' ? e.target.id : e.target;
    if (allowed.has(s) && keep.has(s)) allowed.add(t);
    if (allowed.has(t) && keep.has(t)) allowed.add(s);
  });

  if (allowed.size >= kg.nodes.length) {
    return { ...kg, densified: false, hidden_count: 0 };
  }

  const nodes = kg.nodes.filter((n) => allowed.has(n.id));
  const idSet = new Set(nodes.map((n) => n.id));
  const edges = (kg.edges || []).filter((e) => {
    const s = typeof e.source === 'object' ? e.source.id : e.source;
    const t = typeof e.target === 'object' ? e.target.id : e.target;
    return idSet.has(s) && idSet.has(t);
  });

  return {
    ...kg,
    nodes,
    edges,
    densified: true,
    hidden_count: kg.nodes.length - nodes.length,
    stats: { node_count: nodes.length, edge_count: edges.length },
  };
}

/** Whether to paint a text label for this node given density mode. */
export function shouldPaintLabel(node, {
  mode = 'auto',
  nodeCount = 0,
  isSelected = false,
  isNeighbor = false,
  hubDegree = 2,
} = {}) {
  if (isSelected || isNeighbor) return true;
  if (mode === 'all') return true;
  if (mode === 'hubs') return (node.degree || 0) >= hubDegree;
  // auto
  if (nodeCount <= 40) return true;
  if (nodeCount <= 80) return (node.degree || 0) >= 2 || (node.__colIndex ?? 99) < 8;
  return (node.degree || 0) >= 3 || (node.__colIndex ?? 99) < 6;
}

function edgeEndpointId(end) {
  if (end == null) return null;
  if (typeof end === 'object') return end.id ?? end;
  return end;
}

export function getNodeDetails(nodeId, kg) {
  if (!nodeId || !kg?.nodes) return null;
  const node = kg.nodes.find((n) => n.id === nodeId);
  if (!node) return null;

  const byId = Object.fromEntries(kg.nodes.map((n) => [n.id, n]));
  const meta = TYPE_META[node.type] || TYPE_META.symptom;

  const neighbors = [];
  (kg.edges || []).forEach((e) => {
    const src = edgeEndpointId(e.source);
    const tgt = edgeEndpointId(e.target);
    let otherId = null;
    let direction = 'linked';
    if (src === nodeId) {
      otherId = tgt;
      direction = 'outgoing';
    } else if (tgt === nodeId) {
      otherId = src;
      direction = 'incoming';
    }
    if (!otherId) return;
    const other = byId[otherId];
    if (!other) return;
    neighbors.push({
      node: other,
      edge: e,
      direction,
      kind: e.kind || 'adverse',
    });
  });

  neighbors.sort((a, b) => {
    const tier = (s) => ({ STRONG: 3, MODERATE: 2, Medium: 2, WEAK: 1 }[s] || 0);
    const score = (n) =>
      tier(n.edge.strength) * 1000
      + (n.edge.prr ?? 0) * 10
      + (n.edge.confidence ?? 0) * 5
      + (n.node.degree || 0);
    return score(b) - score(a);
  });

  const relatedPaths = (kg.paths || []).filter((p) => {
    const lbl = (node.label || '').toLowerCase();
    if (node.type === 'drug') return (p.drug || '').toLowerCase() === lbl;
    if (node.type === 'symptom') return (p.symptom || '').toLowerCase() === lbl;
    if (node.type === 'condition') return (p.condition || '').toLowerCase() === lbl;
    if (node.type === 'region') return (p.regions || []).some((r) => r.toLowerCase() === lbl);
    if (node.type === 'protein') {
      return (p.drug || '').toLowerCase() && neighbors.some((nb) => nb.node.type === 'drug');
    }
    return false;
  });

  const byKind = {};
  neighbors.forEach((n) => {
    byKind[n.kind] = byKind[n.kind] || [];
    byKind[n.kind].push(n);
  });

  const neighborTypeCounts = {};
  neighbors.forEach((n) => {
    const t = n.node.type || 'other';
    neighborTypeCounts[t] = (neighborTypeCounts[t] || 0) + 1;
  });

  // Aggregate PRR / strength from adverse edges touching this node
  const adverseEdges = neighbors.filter((n) => n.kind === 'adverse');
  const prrs = adverseEdges.map((n) => n.edge.prr).filter((v) => v != null);
  const strengths = adverseEdges.map((n) => n.edge.strength).filter(Boolean);
  const strengthRank = { STRONG: 3, MODERATE: 2, Medium: 2, WEAK: 1 };
  const topStrength = strengths.length
    ? strengths.reduce((best, s) => (strengthRank[s] || 0) > (strengthRank[best] || 0) ? s : best, strengths[0])
    : null;
  const strengthCounts = { STRONG: 0, MODERATE: 0, WEAK: 0 };
  strengths.forEach((s) => {
    const key = s === 'Medium' ? 'MODERATE' : (strengthCounts[s] != null ? s : 'WEAK');
    strengthCounts[key] = (strengthCounts[key] || 0) + 1;
  });
  const confidences = neighbors
    .map((n) => n.edge.confidence ?? n.node.confidence)
    .filter((v) => v != null);

  return {
    node,
    meta,
    degree: node.degree ?? neighbors.length,
    centrality: node.centrality,
    neighbors,
    byKind,
    neighborTypeCounts,
    relatedPaths: relatedPaths.slice(0, 12),
    stats: {
      adverseLinks: adverseEdges.length,
      maxPrr: prrs.length ? Math.max(...prrs) : null,
      avgPrr: prrs.length ? +(prrs.reduce((a, b) => a + b, 0) / prrs.length).toFixed(2) : null,
      topStrength,
      strengthCounts,
      maxConfidence: confidences.length ? Math.max(...confidences) : null,
      targetKind: node.target_kind || null,
    },
  };
}
