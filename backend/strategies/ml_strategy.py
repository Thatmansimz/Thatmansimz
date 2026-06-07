"""
ML Strategy — wraps the AIEngine and exposes it as a BaseStrategy subclass.
This allows the strategy to be used interchangeably with rule-based strategies
and combined in a meta-strategy ensemble.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class MLStrategy(BaseStrategy):
    """
    Machine-learning strategy backed by the AIEngine ensemble model.
    Delegates all prediction and signal generation to AIEngine, but
    exposes the standard BaseStrategy interface for the scheduler.
    """

    name = "ml_ensemble"
    description = "Gradient Boosting + Random Forest ensemble with 25+ technical features"

    def __init__(self, ai_engine, config=None):
        super().__init__(config)
        self.ai_engine = ai_engine
        self._confidence_threshold = getattr(config, "AI_CONFIDENCE_THRESHOLD", 0.65) if config else 0.65
        self._max_stop_dollars = getattr(config, "MAX_STOP_LOSS_DOLLARS", 250.0) if config else 250.0
        self._min_rr = getattr(config, "MIN_RISK_REWARD_RATIO", 2.0) if config else 2.0

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[dict]:
        """
        Run the AI engine on the supplied DataFrame and return a signal dict.
        Returns None if no high-confidence setup is found.
        """
        if df.empty or len(df) < 50:
            return None

        # Determine point value for the symbol
        point_value_map = {"MES": 5.0, "MNQ": 2.0, "MGC": 10.0}
        point_value = point_value_map.get(symbol.upper(), 5.0)

        signal_dict = self.ai_engine.generate_signal(
            symbol=symbol,
            confidence_threshold=self._confidence_threshold,
            max_stop_dollars=self._max_stop_dollars,
            min_rr=self._min_rr,
            futures_point_value=point_value,
        )

        return signal_dict

    def train(self, df: pd.DataFrame, symbol: str) -> dict:
        """Delegate model training to the AI engine."""
        return self.ai_engine.train(symbol)

    def is_trained(self, symbol: str) -> bool:
        return self.ai_engine.is_trained(symbol) if hasattr(self.ai_engine, "is_trained") else symbol in self.ai_engine.models

    def get_feature_importance(self, symbol: str) -> dict:
        """
        Return feature importance from the trained model (if available).
        Only GradientBoosting supports feature_importances_ natively.
        """
        model = self.ai_engine.models.get(symbol)
        if model is None:
            return {}

        try:
            from backend.services.ai_engine import FEATURE_COLS
            estimator = model.named_steps.get("model")
            if hasattr(estimator, "feature_importances_"):
                importances = estimator.feature_importances_
            elif hasattr(estimator, "estimators_"):
                # VotingClassifier — average from sub-estimators
                importances_list = []
                for _, est in estimator.estimators:
                    if hasattr(est, "feature_importances_"):
                        importances_list.append(est.feature_importances_)
                if importances_list:
                    import numpy as np
                    importances = np.mean(importances_list, axis=0)
                else:
                    return {}
            else:
                return {}

            return dict(zip(FEATURE_COLS, [round(float(v), 6) for v in importances]))
        except Exception as exc:
            logger.warning("Could not extract feature importance for %s: %s", symbol, exc)
            return {}
