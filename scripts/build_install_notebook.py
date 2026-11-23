"""Build the self-contained customer installer without tenant configuration."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATHS = (
    "notebooks/classify_use_cases.py",
    "notebooks/collect_capacity_history.py",
    "notebooks/initialize_capacity_scenarios.py",
    "scripts/create_consumption_preview_views.sql",
    "scripts/create_capacity_scenario_views.sql",
    "scripts/validate_monitoring_model.dax",
)
PARAMETERS = '''# Run interactively in the destination workspace. No Lakehouse attachment required.
source_workspace_id = ""  # Empty means FUAM is in this workspace.
source_lakehouse_name = "FUAM_Lakehouse"
installation_prefix = "UseCaseMonitoring"

# One mapping per capacity. Replace these placeholders with your own resource IDs.
metric_sources = [
    {"capacity_id": "", "workspace_id": "", "model_id": ""}
]

# Optional one-time seeds; use real Fabric Domain tag UUIDs, never display-name matching.
initial_use_cases = []
initial_estimates = []
sql_connection_id = ""  # Optional when exactly one matching authorized connection exists.
focus_date = ""  # Defaults to the latest stored metric day; percentages may be blank.
operation = "install"  # "refresh" reruns collectors and refreshes the Import model.
'''


def build_install_notebook(root: Path = ROOT) -> dict:
    files = {path: root.joinpath(*path.split("/")).read_text(encoding="utf-8") for path in PACKAGE_PATHS}
    modules = []
    for filename in ("build_monitoring_model.py", "build_monitoring_report.py", "install_monitoring.py"):
        source = (root / "scripts" / filename).read_text(encoding="utf-8")
        modules.append(source.split('if __name__ == "__main__":', 1)[0])
    files["_implementation_sha256"] = hashlib.sha256("\n".join(modules).encode()).hexdigest()
    # Keep embedded cell markers out of Fabric's Git source converter.
    encoded = base64.b64encode(json.dumps(files).encode("utf-8")).decode("ascii")
    code = "\n".join(modules) + "\nPACKAGE_FILES = json.loads(base64.b64decode(" + repr(encoded) + "))\n"
    invocation = '''installation = install_in_fabric({
        "source_workspace_id": source_workspace_id,
    "source_lakehouse_name": source_lakehouse_name,
    "prefix": installation_prefix,
    "metric_sources": metric_sources,
    "initial_use_cases": initial_use_cases,
    "initial_estimates": initial_estimates,
    "connection_id": sql_connection_id,
    "focus_date": focus_date,
    "operation": operation,
}, PACKAGE_FILES, build_model, build_report)
'''
    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": [
            "# Fabric Use-Case Monitoring: single-notebook installer\n",
            "Requires existing FUAM/Capacity Metrics data and authorized user identity. ",
            "Review the parameter cell, then Run all. It creates only monitoring resources. ",
            "Missing SQL credentials require a Service connection, then rerun to resume. ",
            "No capacities, permissions, source models, billing certification or automatic schedules are created. ",
            "The embedded package is self-contained; no runtime GitHub downloads.\n",
        ]},
    ]
    for index, source in enumerate((PARAMETERS, code, invocation)):
        cells.append({
            "cell_type": "code", "metadata": {"tags": ["parameters"]} if index == 0 else {},
            "source": source.splitlines(keepends=True), "execution_count": None, "outputs": [],
        })
    return {
        "nbformat": 4, "nbformat_minor": 5, "cells": cells,
        "metadata": {"kernel_info": {"name": "synapse_pyspark"},
                     "language_info": {"name": "python"}, "dependencies": {}},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "notebooks" / "Install_UseCase_Monitoring.ipynb")
    args = parser.parse_args()
    args.output.write_text(json.dumps(build_install_notebook(), indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
