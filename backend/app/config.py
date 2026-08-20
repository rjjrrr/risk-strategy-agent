from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = ROOT / "backend" / "uploads"
OUTPUT_DIR = ROOT / "backend" / "outputs"
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
