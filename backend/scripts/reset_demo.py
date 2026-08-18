"""命令行壳：python scripts/reset_demo.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.demo import reset_demo

if __name__ == "__main__":
    print(reset_demo()["message"])
