"""Validate only this repository's demo lab and write its own report."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'internal'))

from aks_validation import AksLab
from lab_validation import main

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = AksLab(
    ROOT,
    "azure-kubernetes-agentic-ops-eval",
    "rg-agentic-ops-lab",
    "scripts/environment",
)

if __name__ == "__main__":
    raise SystemExit(main(ADAPTER))
