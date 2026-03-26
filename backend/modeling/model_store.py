"""
backend/modeling/model_store.py

Thin helpers for saving and loading model artifacts with pickle.
"""

from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import Any
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = os.environ.get("MODEL_ARTIFACT_PATH", "models/nrfi_model.pkl")


class CalibratedModel:
    """
    Platt scaling wrapper: applies a 2-parameter logistic regression on raw
    model scores from a held-out val set.  Fully picklable from any script
    because it lives in a stable module (not __main__).
    """

    def __init__(self, base_model: Any, calibrator: Any) -> None:
        self.base_model = base_model
        self.calibrator = calibrator

    def predict_proba(self, X: Any) -> Any:
        import numpy as np
        raw = self.base_model.predict_proba(X)[:, 1].reshape(-1, 1)
        return self.calibrator.predict_proba(raw)

    def predict(self, X: Any) -> Any:
        import numpy as np
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def save_model(model: Any, path: str = DEFAULT_MODEL_PATH) -> None:
    """Serialize model to disk. Creates parent directories if needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(model, f)
    logger.info("Model saved to %s", p)


def load_model(path: str = DEFAULT_MODEL_PATH) -> Any:
    """Load and return a model artifact from disk."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No model artifact found at {p}")
    with open(p, "rb") as f:
        model = pickle.load(f)
    logger.info("Model loaded from %s", p)
    return model
