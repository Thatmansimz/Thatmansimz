"""Release-level restrictions. Evidence review is not a client-side checkbox.

This release can inspect research and simulate execution. There is deliberately
no environment flag or API payload that promotes it into a live trading system.
"""
LIVE_PILOT_AVAILABLE = False
FORWARD_RUN_AVAILABLE = False


def require_paper_broker(name: str) -> None:
    if name.lower() != "paper":
        raise ValueError(
            "Broker routing is blocked: the six evidence gates, a completed "
            "adapter and separate pilot authorization have not been verified."
        )


def readiness_status() -> dict:
    return {
        "live_pilot_available": LIVE_PILOT_AVAILABLE,
        "forward_run_available": FORWARD_RUN_AVAILABLE,
        "verified_gates": 0,
        "required_gates": 6,
        "reason": "No frozen forward experiment or reviewed live-pilot evidence is registered.",
    }
