/** Client-side KG filtering (instant UI; works with SPARQL + legacy graph shapes). */

const norm = (s) => (s || '').toLowerCase().trim();

export function labelMatches(node, filter) {
  if (!filter) return true;
  if (!node?.label) return false;
  const l = norm(node.label);
  const f = norm(filter);
  return l === f || l.includes(f);
}

function edgeEnds(e) {
  const s = typeof e.source === 'object' ? e.source.id : e.source;
  const t = typeof e.target === 'object' ? e.target.id : e.target;
  return [s, t];
}

/** Adverse events linked to a drug label (from paths + adverse edges), ranked by PRR. */
export function adverseEventsForDrug(kg, drugLabel) {
  if (!kg || !drugLabel) return [];
  const want = norm(drugLabel);
  const byAe = new Map();

  (kg.paths || []).forEach((p) => {
    if (norm(p.drug) !== want && !norm(p.drug).includes(want)) return;
    const ae = (p.symptom || '').trim();
    if (!ae) return;
    const key = norm(ae);
    const prev = byAe.get(key);
    const prr = p.prr != null ? Number(p.prr) : null;
    if (!prev || (prr != null && (prev.prr == null || prr > prev.prr))) {
      byAe.set(key, {
        symptom: ae,
        prr,
        strength: p.strength || null,
        regions: p.regions || [],
        condition: p.condition || null,
        drug: p.drug,
      });
    }
  });

  const byId = Object.fromEntries((kg.nodes || []).map((n) => [n.id, n]));
  (kg.edges || []).forEach((e) => {
    if ((e.kind || 'adverse') !== 'adverse') return;
    const [sid, tid] = edgeEnds(e);
    const a = byId[sid];
    const b = byId[tid];
    const drugNode = a?.type === 'drug' ? a : b?.type === 'drug' ? b : null;
    const symNode = a?.type === 'symptom' ? a : b?.type === 'symptom' ? b : null;
    if (!drugNode || !symNode) return;
    if (norm(drugNode.label) !== want && !norm(drugNode.label).includes(want)) return;
    const ae = (symNode.label || '').trim();
    if (!ae) return;
    const key = norm(ae);
    if (byAe.has(key)) {
      const prev = byAe.get(key);
      if (e.prr != null && (prev.prr == null || e.prr > prev.prr)) {
        prev.prr = e.prr;
        prev.strength = e.strength || prev.strength;
      }
      prev.nodeId = symNode.id;
      return;
    }
    byAe.set(key, {
      symptom: ae,
      prr: e.prr != null ? Number(e.prr) : null,
      strength: e.strength || null,
      regions: [],
      condition: null,
      drug: drugNode.label,
      nodeId: symNode.id,
    });
  });

  // Attach node ids from graph when missing
  (kg.nodes || []).forEach((n) => {
    if (n.type !== 'symptom') return;
    const hit = byAe.get(norm(n.label));
    if (hit && !hit.nodeId) hit.nodeId = n.id;
  });

  const tier = (s) => ({ STRONG: 3, MODERATE: 2, Medium: 2, WEAK: 1 }[s] || 0);
  return [...byAe.values()].sort(
    (a, b) => tier(b.strength) - tier(a.strength) || (b.prr || 0) - (a.prr || 0) || a.symptom.localeCompare(b.symptom),
  );
}

/** Drugs linked to a symptom/AE label (paths + adverse edges). */
export function drugsForAdverseEvent(kg, symptomLabel) {
  if (!kg || !symptomLabel) return [];
  const want = norm(symptomLabel);
  const byDrug = new Map();

  (kg.paths || []).forEach((p) => {
    if (norm(p.symptom) !== want && !norm(p.symptom).includes(want) && !want.includes(norm(p.symptom))) return;
    const d = (p.drug || '').trim();
    if (!d) return;
    const key = norm(d);
    const prev = byDrug.get(key);
    if (!prev || (p.prr != null && (prev.prr == null || p.prr > prev.prr))) {
      byDrug.set(key, {
        drug: d,
        prr: p.prr != null ? Number(p.prr) : null,
        strength: p.strength || null,
      });
    }
  });

  const byId = Object.fromEntries((kg.nodes || []).map((n) => [n.id, n]));
  (kg.edges || []).forEach((e) => {
    if ((e.kind || 'adverse') !== 'adverse') return;
    const [sid, tid] = edgeEnds(e);
    const a = byId[sid];
    const b = byId[tid];
    const drugNode = a?.type === 'drug' ? a : b?.type === 'drug' ? b : null;
    const symNode = a?.type === 'symptom' ? a : b?.type === 'symptom' ? b : null;
    if (!drugNode || !symNode) return;
    if (norm(symNode.label) !== want && !norm(symNode.label).includes(want) && !want.includes(norm(symNode.label))) return;
    const d = (drugNode.label || '').trim();
    if (!d) return;
    const key = norm(d);
    const prev = byDrug.get(key);
    const prr = e.prr != null ? Number(e.prr) : null;
    if (!prev || (prr != null && (prev.prr == null || prr > prev.prr))) {
      byDrug.set(key, {
        drug: d,
        prr,
        strength: e.strength || prev?.strength || null,
        nodeId: drugNode.id,
      });
    } else if (prev && !prev.nodeId) {
      prev.nodeId = drugNode.id;
    }
  });

  const tier = (s) => ({ STRONG: 3, MODERATE: 2, Medium: 2, WEAK: 1 }[s] || 0);
  return [...byDrug.values()].sort(
    (a, b) => tier(b.strength) - tier(a.strength) || (b.prr || 0) - (a.prr || 0) || a.drug.localeCompare(b.drug),
  );
}

export function filterGraph(kg, { drug = '', symptom = '', condition = '', country = '' } = {}, focusNode = null) {
  if (!kg?.nodes?.length) return kg;

  const hasFilter = drug || symptom || condition || country;
  if (!hasFilter && !focusNode) return kg;

  const byId = Object.fromEntries(kg.nodes.map((n) => [n.id, n]));

  let edges = (kg.edges || []).filter((e) => {
    const a = byId[e.source];
    const b = byId[e.target];
    const kind = e.kind || 'adverse';

    if (kind === 'adverse' || kind === 'indication') {
      const drugNode = a?.type === 'drug' ? a : b?.type === 'drug' ? b : null;
      const symNode = a?.type === 'symptom' ? a : b?.type === 'symptom' ? b : null;
      const condNode = a?.type === 'condition' ? a : b?.type === 'condition' ? b : null;

      if (drug && !labelMatches(drugNode, drug)) return false;
      if (symptom && !labelMatches(symNode, symptom)) return false;
      if (condition && kind === 'indication' && !labelMatches(condNode, condition)) return false;
      if (condition && kind === 'adverse' && condNode && !labelMatches(condNode, condition)) return false;
      return true;
    }

    if (kind === 'condition') {
      const drugNode = a?.type === 'drug' ? a : b?.type === 'drug' ? b : null;
      const condNode = a?.type === 'condition' ? a : b?.type === 'condition' ? b : null;
      if (drug && !labelMatches(drugNode, drug)) return false;
      if (condition && !labelMatches(condNode, condition)) return false;
      return true;
    }

    if (kind === 'region') {
      const regNode = a?.type === 'region' ? a : b?.type === 'region' ? b : null;
      const symNode = a?.type === 'symptom' ? a : b?.type === 'symptom' ? b : null;
      if (country && !labelMatches(regNode, country)) return false;
      if (symptom && !labelMatches(symNode, symptom)) return false;
      if (drug) return true; // region edges don't carry drug; keep if symptom matches
      return true;
    }

    if (kind === 'binds') {
      const drugNode = a?.type === 'drug' ? a : b?.type === 'drug' ? b : null;
      if (drug && !labelMatches(drugNode, drug)) return false;
      // protein edges are drug-scoped; keep when no drug filter or drug matches
      return true;
    }

    return true;
  });

  // Country filter: keep only adverse paths that have a matching region edge
  if (country) {
    const regionEdges = (kg.edges || []).filter((e) => e.kind === 'region');
    const symWithGeo = new Set();
    regionEdges.forEach((e) => {
      const a = byId[e.source];
      const b = byId[e.target];
      const reg = a?.type === 'region' ? a : b?.type === 'region' ? b : null;
      const sym = a?.type === 'symptom' ? a : b?.type === 'symptom' ? b : null;
      if (labelMatches(reg, country) && sym) symWithGeo.add(sym.id);
    });
    edges = edges.filter((e) => {
      if (e.kind !== 'adverse' && e.kind !== 'indication') return true;
      const a = byId[e.source];
      const b = byId[e.target];
      const sym = a?.type === 'symptom' ? a : b?.type === 'symptom' ? b : null;
      return sym && symWithGeo.has(sym.id);
    });
  }

  const activeIds = new Set();
  edges.forEach((e) => {
    activeIds.add(e.source);
    activeIds.add(e.target);
  });

  let nodes = kg.nodes.filter((n) => activeIds.has(n.id));

  if (focusNode) {
    const focusIds = new Set([focusNode]);
    edges.forEach((e) => {
      if (e.source === focusNode) focusIds.add(e.target);
      if (e.target === focusNode) focusIds.add(e.source);
    });
    nodes = nodes.filter((n) => focusIds.has(n.id));
    edges = edges.filter((e) => focusIds.has(e.source) && focusIds.has(e.target));
  }

  const paths = (kg.paths || []).filter((p) => {
    if (drug && norm(p.drug) !== norm(drug) && !norm(p.drug).includes(norm(drug))) return false;
    if (symptom && norm(p.symptom) !== norm(symptom) && !norm(p.symptom).includes(norm(symptom))) return false;
    if (condition && p.condition && norm(p.condition) !== norm(condition)) return false;
    return true;
  });

  const storyText = buildFilterStory({ drug, symptom, condition, country }, nodes.length, edges.length, kg);

  // Prefer structured briefing from server; when client-filtering, rebuild a compact briefing
  const topPaths = (paths || []).slice(0, 8).map((p) => ({
    drug: p.drug,
    symptom: p.symptom,
    prr: p.prr,
    strength: p.strength,
    regions: p.regions || [],
    condition: p.condition,
  }));

  const briefing = storyText
    ? {
        text: storyText,
        summary: storyText,
        source: 'briefing',
        path_count: paths.length,
        node_count: nodes.length,
        edge_count: edges.length,
        top_paths: topPaths,
        filters: { drug, symptom, condition, country },
        disclaimer:
          'Briefing from social-listening extractions; PRR can inflate at small N.',
      }
    : kg.story;

  return {
    ...kg,
    nodes,
    edges,
    paths,
    stats: { node_count: nodes.length, edge_count: edges.length },
    story: briefing,
    filters: { drug, symptom, condition, country, focus_node: focusNode },
    filtered: hasFilter || !!focusNode,
  };
}

function buildFilterStory(filters, nodeCount, edgeCount, kg) {
  const parts = [];
  const active = Object.entries(filters).filter(([, v]) => v);
  if (!active.length) return null;
  const lead = (kg.paths || [])[0];
  const leadBit = lead?.drug && lead?.symptom
    ? ` Strongest listed: ${lead.drug} → ${lead.symptom}${lead.prr != null ? ` (PRR ${lead.prr})` : ''}.`
    : '';
  parts.push(
    `Filtered view (${active.map(([k, v]) => `${k}=${v}`).join(', ')}): `
    + `${nodeCount} nodes / ${edgeCount} edges`
    + (kg.stats ? ` from ${kg.stats.node_count} total.` : '.')
    + leadBit,
  );
  if (nodeCount === 0) {
    parts.push(' No paths match — clear a filter or pick another value.');
  }
  return parts.join('');
}
