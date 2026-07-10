"""Tests for reproducibility manifests."""

from __future__ import annotations

import gzip
import json

from cobra import Model

from src.core.models import GapFillResult, ReactionEvidence
from src.utils.config import Config
from src.utils.provenance import (
    build_gapfill_manifest,
    file_record,
    write_evidence_snapshot,
    write_manifest,
)


def test_file_record_hashes_exact_content(tmp_path) -> None:
    path = tmp_path / "input.txt"
    path.write_bytes(b"abc")
    record = file_record(path)
    assert record is not None
    assert record["bytes"] == 3
    assert record["sha256"] == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_gapfill_manifest_captures_inputs_policy_and_solver(tmp_path) -> None:
    task_file = tmp_path / "tasks.csv"
    task_file.write_text("Task ID\n", encoding="utf-8")
    result = GapFillResult(total_tasks=2, tasks_fixed=1)
    result.evidence_results = {"R1": ReactionEvidence(reaction_id="R1")}

    manifest = build_gapfill_manifest(
        config=Config(),
        result=result,
        model=Model("m"),
        inputs={"task_file": task_file},
        outputs={},
        command=["metatask-gapfill-cli", "model.xml"],
    )

    assert manifest["inputs"]["task_file"]["sha256"]
    assert manifest["penalty_policy"]["tier_base_penalty"]["high"] == 1.0
    assert manifest["external_evidence"]["database_release"] == ("unavailable_from_rest_api")
    assert manifest["command"] == ["metatask-gapfill-cli", "model.xml"]
    assert "optlang_interface" in manifest["solver"]

    output = write_manifest(tmp_path / "run.manifest.json", manifest)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["result"]["tasks_fixed"] == 1


def test_evidence_snapshot_is_deterministic_and_complete(tmp_path) -> None:
    evidence = ReactionEvidence(reaction_id="R1")
    evidence.kegg_reaction_ids = ["R00001"]
    result = GapFillResult(evidence_results={"R1": evidence})
    first = write_evidence_snapshot(tmp_path / "first.json.gz", result)
    second = write_evidence_snapshot(tmp_path / "second.json.gz", result)

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(gzip.decompress(first.read_bytes()))
    assert payload["records"]["R1"]["kegg_reaction_ids"] == ["R00001"]
