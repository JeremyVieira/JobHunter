"""Learn what you like from what you apply to and what you dismiss.

This is *preference* learning, not callback prediction: applying signals "I
wanted this", dismissing signals "I didn't". A smoothed log-odds score over
title words/bigrams and company names nudges new postings up or down by at most
``max_adjustment`` points, and only once there are enough examples of both kinds.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from jobhunter.textutils import normalize_text

_STOP = frozenset(
    "a an the and or of for to in at with junior senior jr sr i ii iii montreal quebec "
    "qc remote hybrid canada ca h f m de du des la le les et en pour".split()
)


def _title_features(title: str) -> set[str]:
    tokens = [t for t in normalize_text(title).split() if len(t) > 1 and t not in _STOP]
    features = {f"t:{token}" for token in tokens}
    features.update(f"t:{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False))
    return features


def _company_feature(company: str) -> str | None:
    norm = normalize_text(company)
    return f"c:{norm}" if norm and norm != "unknown" else None


class FeedbackModel:
    def __init__(
        self,
        liked: Iterable[dict[str, Any]] = (),
        disliked: Iterable[dict[str, Any]] = (),
        *,
        min_examples: int = 30,
        min_per_class: int = 5,
        max_adjustment: float = 8.0,
    ):
        liked = list(liked)
        disliked = list(disliked)
        self.n_liked = len(liked)
        self.n_disliked = len(disliked)
        self.max_adjustment = max_adjustment
        self.active = (
            self.n_liked + self.n_disliked >= min_examples
            and min(self.n_liked, self.n_disliked) >= min_per_class
        )
        self._like: dict[str, int] = {}
        self._dislike: dict[str, int] = {}
        if not self.active:
            return
        for rows, bucket in ((liked, self._like), (disliked, self._dislike)):
            for row in rows:
                for feature in self._features(row):
                    bucket[feature] = bucket.get(feature, 0) + 1

    @staticmethod
    def _features(job: dict[str, Any]) -> set[str]:
        features = _title_features(str(job.get("title") or job.get("role") or ""))
        company = _company_feature(str(job.get("company") or ""))
        if company:
            features.add(company)
        return features

    def _log_ratio(self, feature: str) -> float | None:
        like = self._like.get(feature, 0)
        dislike = self._dislike.get(feature, 0)
        if like + dislike < 2:
            return None
        p_dislike = (dislike + 1) / (self.n_disliked + 2)
        p_like = (like + 1) / (self.n_liked + 2)
        return math.log(p_dislike / p_like)

    def adjust(self, job: dict[str, Any]) -> float:
        """Score adjustment in ``[-max_adjustment, +max_adjustment]`` (0 when inactive)."""
        if not self.active:
            return 0.0
        title_ratios = []
        company_term = 0.0
        for feature in self._features(job):
            ratio = self._log_ratio(feature)
            if ratio is None:
                continue
            if feature.startswith("c:"):
                company_term = max(-1.0, min(1.0, ratio)) * 2.0
            else:
                title_ratios.append(ratio)
        title_term = (sum(title_ratios) / len(title_ratios)) * 3.0 if title_ratios else 0.0
        adjustment = -(title_term + company_term)  # dislike-heavy features push the score down
        return round(max(-self.max_adjustment, min(self.max_adjustment, adjustment)), 2)

    def describe(self) -> dict[str, Any]:
        return {"active": self.active, "liked": self.n_liked, "disliked": self.n_disliked}
