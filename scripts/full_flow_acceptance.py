"""Single acceptance entry point for Risk Strategy Agent.

Runs the complete Python regression suite, UI mapping guard, frontend build,
Git whitespace check, secret scan, and default Zhipu binding validation.
No external LLM call is made, so the run is deterministic and cost-free.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8",errors="replace")
if hasattr(sys.stderr,"reconfigure"): sys.stderr.reconfigure(encoding="utf-8",errors="replace")
FRONTEND = ROOT / "frontend"
RESULT = ROOT / "test_artifacts" / "full_flow" / "latest.json"
MAPPING_FILE = FRONTEND / "src" / "i18n" / "businessLabels.ts"

CORE_ENUMS = {
    "PROMISING", "EXPLORATORY", "REVIEW", "REJECTED", "POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE",
    "SUPPORTED", "PARTIALLY_SUPPORTED", "INCONCLUSIVE", "DATA_QUALITY", "LEAKAGE", "LOW_SIGNAL",
    "OVERFITTING", "FEATURE_DRIFT", "REDUNDANCY", "SEGMENT_MIXTURE", "MODEL_MISMATCH", "UNSTABLE_GAIN",
    "INSUFFICIENT_SAMPLE", "NO_ACTION_REQUIRED", "TEST_FEATURE", "TEST_HYPOTHESIS", "REMOVE_FEATURE_ABLATION",
    "MODEL_SWITCH", "MODEL_TUNE", "DATA_CLEAN_PROPOSAL", "FEATURE_TRANSFORM_PROPOSAL", "REQUEST_ANALYSIS",
    "REQUEST_MORE_DATA", "ROLLBACK", "STOP_EXPLORATION", "NO_ACTION", "CURRENT_STATE", "BEST_STATE",
    "LAST_STABLE_STATE", "NOT_STARTED", "RUNNING", "SUCCESS", "FAILED", "WAITING", "SKIPPED", "STALE",
    "CANCELLED", "CANCEL_REQUESTED", "SHADOW_ONLY", "ACTIVE_CANDIDATE", "INSUFFICIENT_DATA",
    "OUT_OF_DISTRIBUTION",
}


def scan_ui_mapping() -> dict:
    mapping = MAPPING_FILE.read_text(encoding="utf-8")
    mapped = {x for x in CORE_ENUMS if re.search(rf"\b{re.escape(x)}\s*:", mapping)}
    findings: list[dict] = []
    technical_only = 0
    text_node = re.compile(r">([^<>{}]+)<")
    dynamic = re.compile(r">\s*\{([^{}]*(?:\.status|\.decision|\.diagnosis|\.action_type|\.outcome)[^{}]*)\}\s*<")
    for path in sorted((FRONTEND / "src").rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or path == MAPPING_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        technical_only += sum(text.count(value) for value in CORE_ENUMS)
        for line_no, line in enumerate(text.splitlines(), 1):
            for node in text_node.findall(line):
                hits = sorted(x for x in CORE_ENUMS if re.search(rf"\b{x}\b", node))
                if hits: findings.append({"file":str(path.relative_to(ROOT)),"line":line_no,"values":hits})
            if "BusinessLabel" not in line:
                for expression in dynamic.findall(line):
                    if "filter(" not in expression and "validation_code" not in expression:
                        findings.append({"file":str(path.relative_to(ROOT)),"line":line_no,"expression":expression.strip()})
    return {"total_mapped":len(mapped),"unmapped_user_visible":len(findings),"technical_only":technical_only,"missing_core_mappings":sorted(CORE_ENUMS-mapped),"findings":findings}


def run(name: str, command: list[str], cwd: Path = ROOT) -> dict:
    completed = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True)
    output = (completed.stdout + completed.stderr).strip()
    print(f"\n[{name}] {'PASS' if completed.returncode == 0 else 'FAIL'}")
    if output: print(output)
    return {"status":"PASS" if completed.returncode == 0 else "FAIL","returncode":completed.returncode,"output":output[-4000:]}


def secret_scan() -> dict:
    excluded={".git","node_modules","dist","runtime","outputs","uploads","test_artifacts","__pycache__"}
    pattern=re.compile(r"(?i)(sk-[a-z0-9_-]{16,}|api[_-]?key\s*[:=]\s*['\"][^'\"]{12,})")
    findings=[]
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts): continue
        if path.suffix.lower() not in {".py",".ts",".tsx",".md",".json",".yaml",".yml",".toml",".env"}: continue
        try:
            if pattern.search(path.read_text(encoding="utf-8",errors="ignore")): findings.append(str(path.relative_to(ROOT)))
        except OSError: pass
    return {"status":"PASS" if not findings else "FAIL","files":findings}


def zhipu_default_check() -> dict:
    from core.llm.bindings import BindingStore
    with tempfile.TemporaryDirectory(prefix="risk_agent_binding_") as tmp:
        row=BindingStore(Path(tmp)/"bindings.sqlite3").ensure_zhipu_default()
    ok=row["provider"]=="ZHIPU_OPENAI_COMPATIBLE" and row["model"]==os.getenv("ZHIPU_MODEL","glm-4-plus") and row["is_default"] and row["key_ref"]=="ZHIPU_API_KEY"
    return {"status":"PASS" if ok else "FAIL","provider":row["provider"],"model":row["model"],"is_default":row["is_default"],"secret_persisted":False}


def main() -> int:
    checks={}
    pytest_tmp=RESULT.parent/f"pytest_{uuid.uuid4().hex[:10]}"
    pytest_tmp.parent.mkdir(parents=True,exist_ok=True)
    try:
        checks["pytest"]=run(
            "Python full regression",
            [sys.executable,"-m","pytest","-q","-p","no:cacheprovider","--basetemp",str(pytest_tmp)],
        )
    finally:
        shutil.rmtree(pytest_tmp,ignore_errors=True)
    mapping=scan_ui_mapping(); checks["ui_mapping"]={"status":"PASS" if not mapping["unmapped_user_visible"] and not mapping["missing_core_mappings"] else "FAIL",**mapping}; print("\n[UI mapping]",checks["ui_mapping"]["status"],json.dumps(mapping,ensure_ascii=False))
    npm="npm.cmd" if os.name=="nt" else "npm"; checks["frontend_build"]=run("Frontend production build",[npm,"run","build"],FRONTEND)
    checks["git_diff"]=run("Git whitespace",["git","diff","--check"])
    checks["secret_scan"]=secret_scan(); print("\n[Secret scan]",checks["secret_scan"])
    checks["zhipu_default"]=zhipu_default_check(); print("\n[Zhipu default]",checks["zhipu_default"])
    decision="FULL_FLOW_PASS" if all(x["status"]=="PASS" for x in checks.values()) else "FULL_FLOW_FAIL"
    payload={"generated_at":datetime.now(timezone.utc).isoformat(),"decision":decision,"checks":checks}
    RESULT.parent.mkdir(parents=True,exist_ok=True); RESULT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"\n{decision}\nResult: {RESULT.relative_to(ROOT)}")
    return 0 if decision=="FULL_FLOW_PASS" else 1


if __name__=="__main__": raise SystemExit(main())
