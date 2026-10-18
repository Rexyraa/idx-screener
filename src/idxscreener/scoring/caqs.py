from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CAQSResult:
    ticker: str
    caqs: float
    label: str


def score_company(ticker: str, metrics: dict[str, float]) -> CAQSResult:
    """Simplified CAQS scoring for the MVP product.

    This mirrors the PRD structure, using the active MVP pillar weights
    F = 0.40, Q = 0.30, T = 0.30.
    """
    f_score = float(metrics.get("f_score", metrics.get("f", 0.5)))
    q_score = float(metrics.get("q_score", metrics.get("q", 0.5)))
    t_score = float(metrics.get("t_score", metrics.get("t", 0.5)))

    weighted = 0.40 * f_score + 0.30 * q_score + 0.30 * t_score
    caqs = min(max(weighted * 100.0, 0.0), 100.0)

    if caqs >= 80:
        label = "Kandidat Kuat"
    elif caqs >= 65:
        label = "Kandidat"
    elif caqs >= 50:
        label = "Netral"
    else:
        label = "Waspada"

    return CAQSResult(ticker=ticker, caqs=caqs, label=label)
