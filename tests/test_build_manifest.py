"""Unit tests for batch build manifest parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.build.build_manifest import (
    BuildJob,
    ManifestError,
    parse_manifest,
    validate_kegg_code,
)


def _write_fasta(path: Path) -> Path:
    path.write_text(">g1\nMKVLA\n")
    return path


def test_validate_kegg_code() -> None:
    assert validate_kegg_code("eco") == (True, "Escherichia coli")
    assert validate_kegg_code("cgb") == (True, "Corynebacterium glutamicum")
    ok, name = validate_kegg_code("xyz")  # unknown but allowed
    assert ok and name is None
    assert validate_kegg_code("") == (False, None)


def test_buildjob_resolve_universe() -> None:
    assert BuildJob(Path("a.faa"), "eco", universe="gramneg").resolve_universe() == "gramneg"
    assert BuildJob(Path("a.faa"), "cgb", gram="positive").resolve_universe() == "grampos"
    assert BuildJob(Path("a.faa"), "eco", gram="-").resolve_universe() == "gramneg"
    assert BuildJob(Path("a.faa"), "eco").resolve_universe() == ""


def test_parse_manifest_valid(tmp_path: Path) -> None:
    eco = _write_fasta(tmp_path / "eco.faa")
    cgb = _write_fasta(tmp_path / "cgb.faa")
    manifest = tmp_path / "m.csv"
    manifest.write_text(
        "fasta,kegg_code,universe,medium,label\n"
        f"{eco},eco,gramneg,M9,E. coli\n"
        f"{cgb},cgb,grampos,,C. glutamicum\n"
    )
    jobs = parse_manifest(manifest)
    assert len(jobs) == 2
    assert jobs[0].kegg_code == "eco" and jobs[0].universe == "gramneg"
    assert jobs[0].label == "E. coli"
    assert jobs[1].kegg_code == "cgb" and jobs[1].resolve_universe() == "grampos"


def test_parse_manifest_tsv(tmp_path: Path) -> None:
    eco = _write_fasta(tmp_path / "eco.faa")
    manifest = tmp_path / "m.tsv"
    manifest.write_text(f"fasta\tkegg_code\n{eco}\teco\n")
    jobs = parse_manifest(manifest)
    assert len(jobs) == 1 and jobs[0].kegg_code == "eco"


def test_parse_manifest_missing_column(tmp_path: Path) -> None:
    manifest = tmp_path / "m.csv"
    manifest.write_text("fasta,label\nx.faa,foo\n")
    with pytest.raises(ManifestError, match="missing required column"):
        parse_manifest(manifest)


def test_parse_manifest_collects_all_row_errors(tmp_path: Path) -> None:
    eco = _write_fasta(tmp_path / "eco.faa")
    manifest = tmp_path / "m.csv"
    manifest.write_text(
        "fasta,kegg_code\n"
        f"{eco},\n"  # missing kegg_code
        "missing.faa,cgb\n"  # missing fasta
    )
    with pytest.raises(ManifestError) as exc:
        parse_manifest(manifest)
    msg = str(exc.value)
    assert "empty 'kegg_code'" in msg
    assert "fasta not found" in msg


def test_parse_manifest_utf8_bom(tmp_path: Path) -> None:
    eco = _write_fasta(tmp_path / "eco.faa")
    manifest = tmp_path / "m.csv"
    manifest.write_bytes(b"\xef\xbb\xbf" + f"fasta,kegg_code\n{eco},eco\n".encode())
    jobs = parse_manifest(manifest)
    assert len(jobs) == 1 and jobs[0].kegg_code == "eco"


def test_parse_manifest_tab_delimited_txt(tmp_path: Path) -> None:
    eco = _write_fasta(tmp_path / "eco.faa")
    manifest = tmp_path / "m.txt"  # .txt extension but tab-delimited
    manifest.write_text(f"fasta\tkegg_code\n{eco}\teco\n")
    jobs = parse_manifest(manifest)
    assert len(jobs) == 1 and jobs[0].kegg_code == "eco"


def test_parse_manifest_ragged_row(tmp_path: Path) -> None:
    # A row with more columns than the header must be reported, not crash.
    eco = _write_fasta(tmp_path / "eco.faa")
    manifest = tmp_path / "m.csv"
    manifest.write_text(f"fasta,kegg_code\n{eco},eco,oops,extra\n")
    with pytest.raises(ManifestError, match="more columns than header"):
        parse_manifest(manifest)


def test_parse_manifest_not_found(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        parse_manifest(tmp_path / "nope.csv")
