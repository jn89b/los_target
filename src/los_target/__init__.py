"""Package entry point: launches the Streamlit intercept-waypoint UI."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    app_path = Path(__file__).resolve().parent / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)], check=True
    )
