/**
 * Instant good/bad/mixed conclusions from Signal Detail numbers.
 * Runs in the browser from the already-loaded signal — no API required.
 */

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmt(v, d = 2) {
  const n = num(v);
  return n == null ? '—' : n.toFixed(d);
}

function product(sig) {
  return sig?.drug || 'this product';
}

function event(sig) {
  return sig?.meddra?.pt || sig?.symptom || 'this event';
}

function nPosts(sig) {
  return Number(sig?.post_count) || 0;
}

/** Overall bottom line for the signal page. */
export function buildBottomLine(sig) {
  if (!sig) return null;
  const productName = product(sig);
  const eventName = event(sig);
  const n = nPosts(sig);
  const strength = String(sig.strength || 'WEAK').toUpperCase();
  const sdr = Boolean(sig.sdr_flag);
  const prr = num(sig.prr);
  const eb05 = num(sig.eb05);
  const ic025 = num(sig.ic025);
  const calOk = Boolean(sig.calibrated_signal);
  const calP = num(sig.calibrated_p);
  const spike = Boolean(sig.spike_flag);
  const crossed = Boolean(sig.maxsprt_crossed || sig.maxsprt?.crossed);
  const trust = String(sig.trust_label || '').toLowerCase();
  let wellDoc = Boolean(sig.well_documented);
  let meanC = num(sig.completeness_detail?.mean_completeness ?? sig.completeness);
  if (meanC != null && meanC < 0.5) wellDoc = false;
  const who = sig.who_umc || 'Unassessable';
  const urgency = sig.triangulation?.urgency_tier || '';

  const alarms = [];
  const coolers = [];

  if (sdr || strength === 'STRONG' || (eb05 != null && eb05 >= 2)) {
    alarms.push(
      `Screening stats are loud (strength ${strength}${sdr ? ', SDR flag on' : ''}${eb05 != null ? `, EB05=${fmt(eb05)}` : ''}).`,
    );
  }
  if (prr != null && prr >= 10 && n < 10) {
    coolers.push(
      `PRR looks enormous (${fmt(prr, 0)}×) but only ${n} report(s) — tiny samples inflate ratios into scary-looking numbers.`,
    );
  } else if (prr != null && prr >= 2 && n >= 3) {
    alarms.push(`PRR ${fmt(prr, 1)} with n=${n} clears a classic screening bar.`);
  }
  if (ic025 != null && ic025 <= 0) {
    coolers.push(
      `IC025 is ${fmt(ic025)} (not > 0) — the cautious Bayesian vote is NOT convinced yet.`,
    );
  }
  if (eb05 != null && eb05 >= 2 && ic025 != null && ic025 <= 0) {
    coolers.push('EB05 and IC025 disagree — mixed Bayesian picture, not a slam dunk.');
  }
  if (calP != null && !calOk) {
    coolers.push(
      `Empirical calibration failed (p≈${calP.toFixed(3)}) — this may sit in the noise floor.`,
    );
  } else if (calOk) {
    alarms.push('Survives empirical calibration — harder to dismiss as pure noise.');
  }
  if (!wellDoc || (meanC != null && meanC < 0.5)) {
    coolers.push(
      `Supporting posts are poorly documented${meanC != null ? ` (completeness ${fmt(meanC)}/1.00)` : ''} — thin evidence to act on.`,
    );
  }
  if (trust === 'low' || trust === 'sybil') {
    coolers.push(`Trust label is '${trust}' — counts may be gamed or coordinated.`);
  }
  if (spike) alarms.push('Recent spike in talk — something changed in the chatter.');
  if (crossed) alarms.push('MaxSPRT boundary crossed — sequential alarm is on.');
  if (who === 'Certain' || who === 'Probable') alarms.push(`Causality lean is ${who}.`);
  else if (who === 'Unlikely' || who === 'Unassessable') {
    coolers.push(`Causality is ${who} — stories do not clearly pin the product.`);
  }
  if (urgency.includes('CRITICAL') || urgency.includes('HIGH')) {
    alarms.push(`Triangulation urgency: ${urgency.replace(/_/g, ' ')}.`);
  } else if (urgency === 'INSUFFICIENT') {
    coolers.push('Triangulation is insufficient across sources.');
  }

  let tone = 'watch';
  let label = 'Worth a look';
  let headline = `${productName} → ${eventName}: not a clear fire, not clearly nothing. Keep on the radar.`;

  const score = alarms.length - coolers.length;
  if (n <= 2 && strength === 'WEAK' && !sdr) {
    tone = 'reassuring';
    label = 'Low concern for now';
    headline = `${productName} → ${eventName}: weak / sparse pattern. No need to escalate on this alone.`;
  } else if (score >= 2 && coolers.length === 0) {
    tone = 'concerning';
    label = 'Elevated concern';
    headline = `${productName} → ${eventName}: several independent alarms agree. Prioritize human review.`;
  } else if (score >= 1 && coolers.length) {
    tone = 'mixed';
    label = 'Mixed — loud but fragile';
    headline = `${productName} → ${eventName}: screening numbers look scary, but quality / calibration / sample-size caveats pull the other way. Watch closely; do not treat as proven harm.`;
  } else if (coolers.length && !alarms.length) {
    tone = 'reassuring';
    label = 'Mostly reassuring';
    headline = `${productName} → ${eventName}: current analytics cool the story more than they heat it.`;
  }

  if (n < 5 && (sdr || (prr != null && prr >= 5) || (eb05 != null && eb05 >= 2))) {
    tone = 'mixed';
    label = 'Mixed — loud but fragile';
    headline = `${productName} → ${eventName}: the dashboard is flashing (SDR / big ratios), but with only ${n} supporting report(s) this is a fragile early flag — investigate, don't conclude.`;
  }

  const nextStep = (tone === 'mixed' || tone === 'watch')
    ? 'Read the supporting posts, check triangulation / FAERS, and wait for more cases before escalating — unless severity or MaxSPRT / calibration also scream.'
    : tone === 'concerning'
      ? 'Route to medical review with the SAR / memo; corroborate on FAERS/MAUDE and labels.'
      : 'No urgent action from these numbers alone; re-check if volume or spike grows.';

  return {
    tone,
    label,
    headline,
    alarms: alarms.slice(0, 5),
    coolers: coolers.slice(0, 5),
    next_step: nextStep,
  };
}

/** Per-panel takeaways for numbers that exist on this signal. */
export function buildPanelConclusions(sig) {
  if (!sig) return [];
  const out = [];
  const n = nPosts(sig);
  const prr = num(sig.prr);
  const ror = num(sig.ror);
  const chi2 = num(sig.chi_square);
  const strength = String(sig.strength || 'WEAK').toUpperCase();
  const sdr = Boolean(sig.sdr_flag);
  const eb05 = num(sig.eb05);
  const ic025 = num(sig.ic025);

  if (prr != null || ror != null) {
    let verdict = 'reassuring';
    let takeaway = 'Disproportionality is weak — these numbers do not argue for a strong signal.';
    if (sdr || strength === 'STRONG') {
      if (n < 8 && prr != null && prr > 20) {
        verdict = 'mixed';
        takeaway = `LOOKS BAD on the surface (SDR / ${strength}, PRR≈${fmt(prr)}) — but with only ${n} reports those huge ratios are often statistical fireworks, not proof. Investigate soon; don't conclude crisis.`;
      } else {
        verdict = 'concerning';
        takeaway = `HOT screening flag (${strength}${sdr ? ', SDR' : ''}). Pair is reported far more than expected — bring a human reviewer in.`;
      }
    } else if (strength === 'MODERATE') {
      verdict = 'watch';
      takeaway = 'Mild-to-moderate excess reporting — worth watching, not an automatic escalate.';
    }
    out.push({
      id: 'disproportionality',
      title: 'Disproportionality (PRR / ROR / χ²)',
      verdict,
      takeaway,
      numbers: `PRR ${fmt(prr)} · ROR ${fmt(ror)} · χ² ${fmt(chi2)} · n=${n} · ${strength}${sdr ? ' · SDR' : ''}`,
    });
  }

  if (eb05 != null || ic025 != null) {
    const ebOk = eb05 != null && eb05 >= 2;
    const icOk = ic025 != null && ic025 > 0;
    let verdict = 'reassuring';
    let takeaway = `After shrinkage, the signal cools (EB05=${fmt(eb05)}, IC025=${fmt(ic025)}). Scary raw ratios are likely small-number noise.`;
    if (ebOk && icOk) {
      verdict = 'concerning';
      takeaway = `Both cautious Bayesian checks agree this is elevated (EB05=${fmt(eb05)}, IC025=${fmt(ic025)}). Harder to shrug off than raw PRR alone.`;
    } else if (ebOk && !icOk) {
      verdict = 'mixed';
      takeaway = `SPLIT: EB05=${fmt(eb05)} clears ≥2 (concerning), but IC025=${fmt(ic025)} is still ≤0 (not convinced). Don't escalate on EB05 alone.`;
    } else if (!ebOk && icOk) {
      verdict = 'mixed';
      takeaway = `IC025 looks positive (${fmt(ic025)}) but EB05 (${fmt(eb05)}) is below 2 — mixed Bayesian picture.`;
    }
    out.push({
      id: 'bayesian',
      title: 'Bayesian shrinkage (EB05 / IC025)',
      verdict,
      takeaway,
      numbers: `EB05 ${fmt(eb05)} · IC025 ${fmt(ic025)}`,
    });
  }

  if (sig.spike_flag != null || sig.trend_score != null) {
    out.push({
      id: 'trend',
      title: 'Trend & spike',
      verdict: sig.spike_flag ? 'concerning' : 'neutral',
      takeaway: sig.spike_flag
        ? `Talk spiked (z=${fmt(sig.spike_z, 1)}). Check Trust + posts — could be real harm, news, or bots.`
        : 'No loud spike right now — volume looks steady.',
      numbers: `spike=${Boolean(sig.spike_flag)} · trend=${fmt(sig.trend_score, 4)}`,
    });
  }

  if (sig.maxsprt_llr != null || sig.maxsprt || sig.maxsprt_crossed) {
    const crossed = Boolean(sig.maxsprt_crossed || sig.maxsprt?.crossed);
    out.push({
      id: 'maxsprt',
      title: 'MaxSPRT',
      verdict: crossed ? 'concerning' : 'reassuring',
      takeaway: crossed
        ? 'Sequential surveillance hit the alarm line — formal flag on accumulating counts.'
        : 'Still under the MaxSPRT stop line — continuous monitoring has not alarmed yet.',
      numbers: `LLR ${fmt(sig.maxsprt_llr ?? sig.maxsprt?.llr)} · crossed=${crossed}`,
    });
  }

  if (sig.hr != null) {
    const elevated = Boolean(sig.hr_elevated) || (num(sig.hr) != null && num(sig.hr) > 1.5);
    out.push({
      id: 'cox',
      title: 'Cox hazard ratio',
      verdict: elevated ? 'concerning' : 'neutral',
      takeaway: elevated
        ? `Timing model says events come faster (HR≈${fmt(sig.hr)}). Supportive — not causation proof.`
        : `Hazard ratio (~${fmt(sig.hr)}) is not clearly elevated — timing evidence is soft.`,
      numbers: `HR ${fmt(sig.hr)}${sig.hr_ci ? ` · CI ${fmt(sig.hr_ci[0])}–${fmt(sig.hr_ci[1])}` : ''}`,
    });
  }

  if (sig.calibrated_p != null || sig.e_value != null || sig.calibration) {
    const calOk = Boolean(sig.calibrated_signal);
    const calP = num(sig.calibrated_p);
    const eVal = num(sig.e_value);
    let takeaway = calOk
      ? 'Survives empirical calibration — less likely pure database noise. Raises priority.'
      : `After comparing to the noise floor, this does NOT clear the bar${calP != null ? ` (p≈${calP.toFixed(3)})` : ''}. Flashy PRR is likely compatible with background chatter — cools the panic.`;
    if (!calOk && eVal != null && eVal > 100) {
      takeaway += ` (Huge E-value ${fmt(eVal)} only means IF this were real it would be hard to confound away — it does not override failed calibration.)`;
    }
    out.push({
      id: 'calibration',
      title: 'Calibration & E-value',
      verdict: calOk ? 'concerning' : 'reassuring',
      takeaway,
      numbers: `calibrated p ${fmt(calP, 4)} · E-value ${fmt(eVal)} · flag=${calOk}`,
    });
  }

  const meanC = num(sig.completeness_detail?.mean_completeness ?? sig.completeness);
  if (meanC != null || sig.completeness_detail) {
    const well = meanC != null ? meanC >= 0.5 : Boolean(sig.well_documented);
    out.push({
      id: 'completeness',
      title: 'Report completeness',
      verdict: well ? 'reassuring' : 'caution',
      takeaway: well
        ? `Documentation looks usable (≈${fmt(meanC)}/1.00) — better ground for review.`
        : `Poorly documented (≈${fmt(meanC)}/1.00, need ≥0.50). Don't escalate on stats alone — stories are thin.`,
      numbers: `mean ${fmt(meanC)} / 1.00`,
    });
  }

  if (sig.who_umc || sig.causality_assessment) {
    const who = sig.who_umc
      || sig.causality_assessment?.who_umc?.category
      || 'Unassessable';
    let verdict = 'reassuring';
    let takeaway = `Causality is ${who} — narratives do not strongly blame the product yet.`;
    if (who === 'Certain' || who === 'Probable') {
      verdict = 'concerning';
      takeaway = `Causality checklist leans ${who} — stories fit a product link better than chance.`;
    } else if (who === 'Possible') {
      verdict = 'watch';
      takeaway = "Causality is only 'Possible' — plausible but not pinned. Common for thin social text.";
    }
    const nar = sig.causality_assessment?.naranjo;
    out.push({
      id: 'causality',
      title: 'Causality (WHO-UMC / Naranjo)',
      verdict,
      takeaway,
      numbers: `WHO-UMC ${who}${nar ? ` · Naranjo ${nar.category} (${nar.score})` : ''}`,
    });
  }

  if (sig.triangulation?.urgency_tier || sig.triangulation?.pillars) {
    const tier = sig.triangulation.urgency_tier || '';
    const nPass = sig.triangulation.n_pillars_passed;
    let verdict = 'mixed';
    let takeaway = `Triangulation: ${tier || 'n/a'}; pillars ${nPass ?? '—'}/3.`;
    if (tier.includes('CRITICAL') || tier.includes('HIGH')) {
      verdict = 'concerning';
      takeaway = `Multiple lenses agree this is urgent (${tier.replace(/_/g, ' ')}). Social is not standing alone.`;
    } else if (nPass === 1 || tier === 'EMERGENT_CHATTER' || tier === 'INSUFFICIENT') {
      verdict = 'watch';
      takeaway = 'Weak multi-source agreement — caution, not conclusion.';
    }
    out.push({
      id: 'triangulation',
      title: 'Evidence triangulation',
      verdict,
      takeaway,
      numbers: sig.triangulation.badge || tier,
    });
  }

  if (sig.trust_score != null || sig.trust_label) {
    const label = String(sig.trust_label || 'high').toLowerCase();
    out.push({
      id: 'trust',
      title: 'Trust / Sybil',
      verdict: (label === 'sybil' || label === 'low') ? 'caution' : label === 'medium' ? 'watch' : 'reassuring',
      takeaway: (label === 'sybil' || label === 'low')
        ? `Trust is ${label} — loud stats may be inflated. Verify before escalating.`
        : label === 'medium'
          ? 'Medium trust — read posts carefully.'
          : 'Trust looks healthy — less likely a spam burst.',
      numbers: `score ${fmt(sig.trust_score)} · ${label}`,
    });
  }

  if (sig.label_filter || sig.label_novelty) {
    const tag = sig.label_filter?.tag || sig.label_filter?.novelty_tier || sig.label_novelty || '';
    const novel = String(tag).toUpperCase().includes('NOVEL') || String(tag).toLowerCase() === 'novel';
    const established = String(tag).toUpperCase().includes('ESTABLISHED') || String(tag).includes('in_label');
    out.push({
      id: 'label',
      title: 'Label vs novel',
      verdict: novel ? 'concerning' : established ? 'reassuring' : 'neutral',
      takeaway: novel
        ? 'Looks NEW vs the label — unexpected events deserve faster eyes.'
        : established
          ? 'Already on-label / established — novelty urgency is lower.'
          : `Label status: ${tag || 'unknown'}.`,
      numbers: String(tag || '—'),
    });
  }

  out.push({
    id: 'four_gate',
    title: '4-gate AE detector',
    verdict: 'neutral',
    takeaway: `${n} post(s) cleared product + symptom + negative tone + not-negated. That is why they count toward this signal.`,
    numbers: `n=${n}`,
  });

  return out;
}

/** Local Q&A over conclusions — works without the API. */
export function answerLocally(sig, question) {
  const q = (question || '').trim();
  const bottom = buildBottomLine(sig);
  const panels = buildPanelConclusions(sig);
  if (!q) {
    return {
      answer: bottom
        ? `**${bottom.label}**\n\n${bottom.headline}\n\nWhat to do: ${bottom.next_step}`
        : 'Open a signal to get conclusions.',
      matched_feature: 'bottom_line',
    };
  }
  const qL = q.toLowerCase();

  if (/bottom.?line|should i worry|is (this|it) (bad|good|safe|serious|okay|ok)|overall|conclude|conclusion|what (should|do) i|summar|escalate/.test(qL)) {
    const bits = [`**${bottom.label}**`, '', bottom.headline, ''];
    if (bottom.alarms?.length) {
      bits.push('Why it looks concerning:');
      bottom.alarms.forEach((a) => bits.push(`• ${a}`));
      bits.push('');
    }
    if (bottom.coolers?.length) {
      bits.push('Why not to panic yet:');
      bottom.coolers.forEach((c) => bits.push(`• ${c}`));
      bits.push('');
    }
    bits.push(`**What to do:** ${bottom.next_step}`);
    return { answer: bits.join('\n'), matched_feature: 'bottom_line', bottom_line: bottom };
  }

  const hints = [
    [/prr|ror|chi|disproport|strength/, 'disproportionality'],
    [/eb05|ic025|bayes|shrink/, 'bayesian'],
    [/spike|trend/, 'trend'],
    [/maxsprt|llr/, 'maxsprt'],
    [/cox|hazard|\bhr\b/, 'cox'],
    [/e-?value|calibrat/, 'calibration'],
    [/completeness|vigigrade|document/, 'completeness'],
    [/naranjo|who-?umc|causalit/, 'causality'],
    [/triangul|faers|maude|pillar/, 'triangulation'],
    [/trust|sybil/, 'trust'],
    [/label|novel/, 'label'],
    [/4-?gate|four.?gate|ae detect/, 'four_gate'],
  ];
  let id = null;
  for (const [re, fid] of hints) {
    if (re.test(qL)) { id = fid; break; }
  }
  const step = panels.find((p) => p.id === id);
  if (step) {
    return {
      answer: `**${step.title}** — ${String(step.verdict).toUpperCase()}\n\n**Bottom line:** ${step.takeaway}\n\nNumbers: ${step.numbers}`,
      matched_feature: step.id,
    };
  }
  return {
    answer: `**${bottom.label}**\n\n${bottom.headline}\n\nAsk about a specific number (PRR, EB05, calibration, completeness) or “Is this bad?”`,
    matched_feature: 'bottom_line',
    bottom_line: bottom,
  };
}
