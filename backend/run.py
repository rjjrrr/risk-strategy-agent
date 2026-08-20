"""Backend development entry point that is independent of the current directory."""

import os
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


if __name__ == "__main__":
    # Uvicorn's reload child resolves import strings again. Keeping its working
    # directory at the repository root makes `backend.app.main` resolvable in
    # both the supervisor and the spawned process on Windows.
    os.chdir(PROJECT_ROOT)
    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT)],
    )
