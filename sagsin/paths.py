"""Paths owned by the integrated runtime, separate from legacy and Second data."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
OUTPUT = ROOT / "data" / "output" / "distributed_fl"
RUNS = Path(os.environ.get("SAGSIN_DATA_DIR", OUTPUT / "runs"))
SECRETS = Path(os.environ.get("SAGSIN_CREDENTIALS", ROOT / ".secrets" / "distributed-fl.json"))

