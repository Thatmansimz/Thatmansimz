import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

from backend.services.market_data import MarketDataService

logger = logging.getLogger(__name__)

MODEL_DIR = "data/models"
os.makedirs(MODEL_DIR, exist_ok=True)

FEATURE_COLS = [
    "rsi", "macd", "macd_signal", "macd_hist",
    "bb_pct", "bb_width",
    "stoch_k", "stoch_d",
    "adx", "plus_di", "minus_di",
    "williams_r", "cci", "roc_10",
    "atr_pct", "rel_volume", "volume_trend",
    "above_ema_9", "above_ema_21", "above_ema_50",
    "price_vs_vwap",
    "body_size", "upper_wick", "lower_wick", "is_bullish",
    "hh_5", "ll_5",
]


class AIEngine:
    def __init__(self, config=None):
        self.config = config
        self.models: dict[str, Pipeline] = {}
        self.market_data = MarketDataService()
        self._load_all_models()

    def _model_path(self, symbol: str) -> str:
        return os.path.join(MODEL_DIR, f"{symbol.lower()}_model.joblib")

    def _load_all_models(self):
        for f in os.listdir(MODEL_DIR):
            if f.endswith("_model.joblib"):
                symbol = f.replace("_model.joblib", "").upper()
                try:
                    self.models[symbol] = joblib.load(os.path.join(MODEL_DIR, f))
                    logger.info("Loaded model for %s", symbol)
                except Exception as exc:
                    logger.warning("Could not load model for %s: %s", symbol, exc)

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        available = [c for c in FEATURE_COLS if c in df.columns]
        missing = set(FEATURE_COLS) - set(available)
        if missing:
            logger.debug("Missing features: %s", missing)
        return df[available].copy()

    def _label_trades(self, df: pd.DataFrame, lookahead: int = 6) -> pd.Series:
        """
        Label each bar:
          1  = long signal  (price rises >0.5% before falling 0.25%)
         -1  = short signal (price falls >0.5% before rising 0.25%)
          0  = neutral
        """
        closes = df["close"].values
        labels = np.zeros(len(closes), dtype=int)
        target_pct = 0.005
        stop_pct = 0.0025

        for i in range(len(closes) - lookahead):
            entry = closes[i]
            long_target = entry * (1 + target_pct)
            long_stop = entry * (1 - stop_pct)
            short_target = entry * (1 - target_pct)
            short_stop = entry * (1 + stop_pct)

            long_hit = short_hit = False
            for j in range(1, lookahead + 1):
                future = closes[i + j]
                if not long_hit and not short_hit:
                    if future >= long_target:
                        long_hit = True
                        break
                    if future <= long_stop:
                        break
                if not long_hit and not short_hit:
                    if future <= short_target:
                        short_hit = True
                        break
                    if future >= short_stop:
                        break

            if long_hit:
                labels[i] = 1
            elif short_hit:
                labels[i] = -1

        return pd.Series(labels, index=df.index, name="label")

    def train(self, symbol: str, period: str = "120d", interval: str = "5m") -> dict:
        logger.info("Training model for %s", symbol)
        df = self.market_data.get_historical(symbol, period=period, interval=interval)
        df = self.market_data.add_indicators(df)

        if len(df) < 200:
            return {"error": f"Insufficient data for {symbol}: {len(df)} bars"}

        labels = self._label_trades(df)
        df["label"] = labels
        df = df.dropna()

        features = self.build_features(df)
        y = df["label"]

        if len(features.columns) == 0:
            return {"error": "No features available after indicator calculation"}

        X_train, X_test, y_train, y_test = train_test_split(
            features, y, test_size=0.2, shuffle=False
        )

        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("model", GradientBoostingClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                min_samples_split=20,
                random_state=42,
            )),
        ])

        pipeline.fit(X_train, y_train)

        y_pred = pipeline.predict(X_test)
        report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)

        self.models[symbol] = pipeline
        joblib.dump(pipeline, self._model_path(symbol))
        logger.info("Model saved for %s", symbol)

        dist = y.value_counts().to_dict()
        return {
            "symbol": symbol,
            "bars_trained": len(X_train),
            "label_distribution": {str(k): int(v) for k, v in dist.items()},
            "test_accuracy": float(report.get("accuracy", 0)),
            "report": {str(k): v for k, v in report.items()},
        }

    def predict(self, symbol: str, df: pd.DataFrame) -> dict:
        if symbol not in self.models:
            return {"direction": "neutral", "confidence": 0.0, "reason": "no_model"}

        features = self.build_features(df)
        if features.empty:
            return {"direction": "neutral", "confidence": 0.0, "reason": "no_features"}

        model = self.models[symbol]
        try:
            expected_features = model.named_steps["scaler"].feature_names_in_
            missing = set(expected_features) - set(features.columns)
            if missing:
                for col in missing:
                    features[col] = 0.0
            features = features[expected_features]
        except AttributeError:
            pass

        last_row = features.iloc[[-1]]
        proba = model.predict_proba(last_row)[0]
        classes = list(model.classes_)

        prob_long = proba[classes.index(1)] if 1 in classes else 0.0
        prob_short = proba[classes.index(-1)] if -1 in classes else 0.0
        prob_neutral = proba[classes.index(0)] if 0 in classes else 0.0

        if prob_long >= prob_short and prob_long > prob_neutral:
            direction = "long"
            confidence = float(prob_long)
        elif prob_short > prob_long and prob_short > prob_neutral:
            direction = "short"
            confidence = float(prob_short)
        else:
            direction = "neutral"
            confidence = float(prob_neutral)

        return {
            "direction": direction,
            "confidence": confidence,
            "prob_long": float(prob_long),
            "prob_short": float(prob_short),
            "prob_neutral": float(prob_neutral),
        }

    def generate_signal(
        self,
        symbol: str,
        confidence_threshold: float = 0.65,
        max_stop_dollars: float = 250.0,
        min_rr: float = 2.0,
        futures_point_value: float = 5.0,
    ) -> Optional[dict]:
        df = self.market_data.get_historical(symbol, period="10d", interval="5m")
        df = self.market_data.add_indicators(df)

        if df.empty or len(df) < 50:
            return None

        prediction = self.predict(symbol, df)
        direction = prediction["direction"]
        confidence = prediction["confidence"]

        if direction == "neutral" or confidence < confidence_threshold:
            return None

        last = df.iloc[-1]
        current_price = float(last["close"])
        atr = float(last.get("atr", current_price * 0.002))

        if direction == "long":
            entry = current_price
            stop_loss = current_price - atr * 1.5
            target_1 = current_price + atr * 3.0
            target_2 = current_price + atr * 5.0
        else:
            entry = current_price
            stop_loss = current_price + atr * 1.5
            target_1 = current_price - atr * 3.0
            target_2 = current_price - atr * 5.0

        stop_distance = abs(entry - stop_loss)
        reward_distance = abs(target_1 - entry)
        rr_ratio = reward_distance / stop_distance if stop_distance > 0 else 0

        # Enforce max stop loss in dollars
        max_contracts = int(max_stop_dollars / (stop_distance * futures_point_value))
        contracts = max(1, min(max_contracts, 10))
        risk_dollars = stop_distance * futures_point_value * contracts

        if rr_ratio < min_rr:
            logger.debug(
                "Signal rejected for %s: R:R %.2f < %.2f", symbol, rr_ratio, min_rr
            )
            return None

        if risk_dollars > max_stop_dollars:
            logger.debug(
                "Signal rejected for %s: risk $%.0f > max $%.0f",
                symbol, risk_dollars, max_stop_dollars,
            )
            return None

        expires_at = datetime.utcnow() + timedelta(minutes=30)

        return {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "prob_long": prediction.get("prob_long", 0),
            "prob_short": prediction.get("prob_short", 0),
            "entry_price": round(entry, 2),
            "entry_zone_low": round(entry - atr * 0.3, 2),
            "entry_zone_high": round(entry + atr * 0.3, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "risk_reward_ratio": round(rr_ratio, 2),
            "risk_amount": round(risk_dollars, 2),
            "reward_amount": round(reward_distance * futures_point_value * contracts, 2),
            "contracts": contracts,
            "timeframe": "5m",
            "strategy": "ai_ensemble",
            "expires_at": expires_at.isoformat(),
            "indicators": {
                "rsi": round(float(last.get("rsi", 0)), 2),
                "macd_hist": round(float(last.get("macd_hist", 0)), 4),
                "adx": round(float(last.get("adx", 0)), 2),
                "stoch_k": round(float(last.get("stoch_k", 0)), 2),
                "rel_volume": round(float(last.get("rel_volume", 1)), 2),
                "atr": round(atr, 2),
            },
        }
