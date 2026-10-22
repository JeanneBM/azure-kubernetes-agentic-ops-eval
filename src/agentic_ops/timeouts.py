"""Shared rollout/handoff budget, validated before either workload starts."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

DEFAULT_VERIFY_TIMEOUT = 120.0
DEFAULT_HANDOFF_TIMEOUT = 180.0
HANDOFF_MARGIN = 30.0


def validate_timeouts(verify_timeout: float, handoff_timeout: float) -> None:
    if not all(math.isfinite(value) and value > 0 for value in (verify_timeout, handoff_timeout)):
        raise ValueError("verification and handoff timeouts must be finite and positive")
    if handoff_timeout <= verify_timeout + HANDOFF_MARGIN:
        raise ValueError("handoff timeout must exceed verification timeout plus a 30-second margin")


@dataclass(frozen=True)
class Timeouts:
    verify: float = DEFAULT_VERIFY_TIMEOUT
    handoff: float = DEFAULT_HANDOFF_TIMEOUT

    def __post_init__(self) -> None:
        validate_timeouts(self.verify, self.handoff)

    @classmethod
    def from_env(cls) -> Timeouts:
        return cls(
            verify=float(os.environ.get("AGENTIC_OPS_VERIFY_TIMEOUT_SECONDS", DEFAULT_VERIFY_TIMEOUT)),
            handoff=float(os.environ.get("AGENTIC_OPS_HANDOFF_TIMEOUT_SECONDS", DEFAULT_HANDOFF_TIMEOUT)),
        )
