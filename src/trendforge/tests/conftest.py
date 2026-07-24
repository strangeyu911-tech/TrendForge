"""pytest 配置 — 将 src/trendforge 加入 path"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
