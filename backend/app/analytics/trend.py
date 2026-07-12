"""Emerging-signal trend & spike detection over time.

New capability (the brief asks for trend/spike analysis; neither source repo had it).
Given the timestamps of AE reports for a drug-symptom pair, we bucket by day,
compute a normalized trend slope, and flag spikes via z-score against history.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import List


def _daily_series(timestamps: List[datetime]) -> List[dict]:
    if not timestamps:
        return []
    days = [ts.date() for ts in timestamps]
    counts = Counter(days)
    start, end = min(days), max(days)
    series = []
    cur = start
    while cur <= end:
        series.append({"date": cur.isoformat(), "count": counts.get(cur, 0)})
        cur += timedelta(days=1)
    return series


def _slope(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den else 0.0


def compute_trend(timestamps: List[datetime]) -> dict:
    series = _daily_series(timestamps)
    if not series:
        return {"series": [], "trend_score": 0.0, "spike_flag": False, "spike_z": 0.0}

    values = [pt["count"] for pt in series]
    slope = _slope([float(v) for v in values])
    # normalize slope by mean level so it is comparable across pairs
    mean_level = (sum(values) / len(values)) or 1.0
    trend_score = round(slope / mean_level, 3)

    # Densified baseline: compare the most recent day against a SMOOTHED expected
    # level (EWMA over history) rather than raw daily counts. Social/report data is
    # bursty and sparse (weekends dip to zero), so a raw day-over-day z-score throws
    # false spikes; smoothing + a variance floor suppresses that noise.
    baseline = _ewma([float(v) for v in values], alpha=0.4)
    series = [{**pt, "baseline": round(baseline[i], 2)} for i, pt in enumerate(series)]

    spike_flag = False
    spike_z = 0.0
    if len(values) >= 4:
        history = values[:-1]
        last = values[-1]
        expected = baseline[-2]  # smoothed level just before the last day
        mean_h = sum(history) / len(history)
        var_h = sum((v - mean_h) ** 2 for v in history) / len(history)
        # variance floor (Poisson-like): sparse-day noise shouldn't inflate z.
        std_h = max(var_h ** 0.5, (mean_h ** 0.5) if mean_h > 0 else 1.0, 1.0)
        spike_z = round((last - expected) / std_h, 3)
        # require a real burst above the smoothed baseline, not just a sparse blip
        spike_flag = spike_z >= 2.0 and last >= max(3, expected + 2)

    return {
        "series": series,
        "trend_score": trend_score,
        "spike_flag": spike_flag,
        "spike_z": spike_z,
    }


def _ewma(values: List[float], alpha: float = 0.4) -> List[float]:
    """Exponentially-weighted moving average (smoothed expected level)."""
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out
