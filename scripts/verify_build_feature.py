#!/usr/bin/env python
"""End-to-end verification for the CarveMe model-construction feature.

Runs the CarveMe toolchain check, optional real CLI builds (single + batch +
refine) on the bundled proteomes, and offscreen GUI screenshots of the Build
panel and the build->evaluator handoff. All artifacts land in ``temp_figures/``.

Usage:
    # Fast: env check + GUI screenshots (uses any pre-built model in temp_figures)
    python scripts/verify_build_feature.py

    # Full: also run real CLI single/batch builds and a refinement
    python scripts/verify_build_feature.py --run-builds

Run from the project root inside the env that has `carve` (e.g. the metatask
conda env).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "temp_figures"
DATA = ROOT / "data"


def _run(cmd: list[str], log: Path | None = None) -> int:
    print(f"\n$ {' '.join(cmd)}")
    if log is not None:
        with log.open("w") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
        tail = log.read_text().splitlines()[-8:]
        print("\n".join(tail))
        return proc.returncode
    return subprocess.run(cmd).returncode


def check_env() -> bool:
    print("=== CarveMe toolchain check ===")
    from src.build.carveme_runner import CarveMeRunner
    from src.utils.config import Config

    cfg = Config.load()
    runner = CarveMeRunner(
        executable=cfg.carveme_executable,
        conda_env=cfg.carveme_env,
        diamond_executable=cfg.carveme_diamond_executable,
    )
    avail = runner.check_available(solver=cfg.carveme_solver)
    print(avail.message)
    return avail.ok


def run_cli_builds() -> None:
    FIG.mkdir(exist_ok=True)
    cli = [sys.executable, "-m", "src.cli"]

    print("\n=== CLI single build (eco) ===")
    _run(
        cli + ["--build", str(DATA / "eco_protein.faa"), "--organism", "eco",
               "--build-output", str(FIG / "eco_built.xml")],
        FIG / "cli_single_eco.log",
    )

    print("\n=== CLI batch build (eco + cgb) ===")
    manifest = FIG / "manifest.csv"
    if not manifest.exists():
        manifest.write_text(
            "fasta,kegg_code,universe,medium,label\n"
            f"{DATA / 'eco_protein.faa'},eco,gramneg,,E. coli\n"
            f"{DATA / 'cgb_protein.faa'},cgb,grampos,,C. glutamicum\n"
        )
    _run(
        cli + ["--batch-build", str(manifest), "--build-output", str(FIG / "built")],
        FIG / "cli_batch.log",
    )

    print("\n=== CLI build + refine (eco) ===")
    _run(
        cli + ["--build", str(DATA / "eco_protein.faa"), "--organism", "eco",
               "--build-output", str(FIG / "eco_refine.xml"), "--refine", "--skip-evaluation",
               "--output-model", str(FIG / "eco_refined.xml"),
               "--output-report", str(FIG / "eco_refine_report.csv")],
        FIG / "cli_refine.log",
    )


def gui_screenshots() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path as _P

    from PySide6.QtWidgets import QApplication, QTableWidgetItem

    from src.build.build_engine import BuiltModel
    from src.build.carveme_runner import CarveMeResult
    from src.core.sbml_parser import SBMLParser
    from src.gui.main_window import MainWindow
    from src.utils.config import Config

    app = QApplication.instance() or QApplication([])
    w = MainWindow(Config.load())
    w.resize(1500, 950)
    w.show()
    app.processEvents()

    bp = w._build_panel
    w._construct_ctrl.open_build_panel()
    bp._fasta_edit.setText(str(DATA / "eco_protein.faa"))
    bp._kegg_edit.setText("eco")
    for line in ("carve data/eco_protein.faa -o eco.xml --solver gurobi -v",
                 "diamond blastp vs reference...", "MILP carving (gurobi)..."):
        bp.append_log(line)
    app.processEvents()
    bp.grab().save(str(FIG / "gui_02_build_panel_single.png"))

    bp._batch_radio.setChecked(True)
    app.processEvents()
    for fasta, code in ((DATA / "eco_protein.faa", "eco"), (DATA / "cgb_protein.faa", "cgb")):
        r = bp._add_batch_row()
        bp._batch_table.setItem(r, 0, QTableWidgetItem(str(fasta)))
        bp._batch_table.setItem(r, 1, QTableWidgetItem(code))
    app.processEvents()
    bp.grab().save(str(FIG / "gui_03_build_panel_batch.png"))

    # Handoff: load a pre-built model into the evaluator if available
    built_xml = FIG / "eco_built.xml"
    if built_xml.exists():
        bp._single_radio.setChecked(True)
        md = SBMLParser().load_model(built_xml)
        md.kegg_organism_code = "eco"
        md.organism = "Escherichia coli"
        built = BuiltModel(
            model_data=md, sbml_path=_P(built_xml), kegg_code="eco",
            carve_result=CarveMeResult(
                fasta_path=DATA / "eco_protein.faa", output_path=_P(built_xml), returncode=0
            ),
        )
        bp.add_built(built, f"{md.id} ({md.reaction_count} rxn, {md.gene_count} gene)", ok=True)
        app.processEvents()
        bp.grab().save(str(FIG / "gui_04_build_result.png"))
        w._construct_ctrl.send_to_evaluator(built)
        app.processEvents()
        w.grab().save(str(FIG / "gui_05_evaluator_loaded.png"))
    app.quit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-builds", action="store_true", help="run real CLI builds (slow)")
    parser.add_argument("--no-gui", action="store_true", help="skip GUI screenshots")
    args = parser.parse_args(argv)

    FIG.mkdir(exist_ok=True)
    ok = check_env()
    if not ok:
        print("CarveMe toolchain not available — aborting.")
        return 1
    if args.run_builds:
        run_cli_builds()
    if not args.no_gui:
        gui_screenshots()
    print(f"\nDone. Artifacts in {FIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
