from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = ROOT / "backend" / "uploads"
OUTPUT_DIR = ROOT / "backend" / "outputs"
MODEL_AGENT_DIR = ROOT / "backend" / "model_agent"
RUNTIME_DIR = ROOT / "backend" / "runtime"
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
