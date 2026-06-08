"""
Tajari V2 — Multi-Session Trading Engine
========================================

Self-contained package implementing the business-partner spec for 24/5
NQ/MNQ trading across Asia, London, and New York sessions. Kept fully
separate from the validated V1 ORB strategy so the two never interfere.

Public entry point:
    from backend.strategies.v2 import MultiSessionStrategy
"""
from backend.strategies.v2.strategy import MultiSessionStrategy

__all__ = ["MultiSessionStrategy"]
