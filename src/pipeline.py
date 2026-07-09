"""YAML-driven CLI pipeline: build (single/batch) → refine in one run.

A pipeline YAML is a one-shot run specification layered on top of the persistent
:class:`~src.utils.config.Config`. It either *builds* models from protein FASTA
(with their KEGG taxonomy codes) or takes existing SBML *models*, then runs
task-aware gap-fill refinement (single model at a time), writing per-model
outputs via ``{label}`` / ``{model}`` templates.

The executor is thin: it parses + validates the spec and delegates to the
existing engines/entry points (:class:`~src.build.build_engine.BuildEngine`,
``src.cli.async_gapfill_main``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.build.carveme_runner import VALID_UNIVERSES
from src.utils.config import Config
from src.utils.constants import KEGG_CODE_TO_NAME

logger = logging.getLogger("metataskgapfill.pipeline")

LogCallback = Callable[[str], None]
_VALID_SOLVERS = ("gurobi", "cplex", "scip")


class PipelineError(ValueError):
    """Raised when a pipeline YAML is malformed or invalid (reports all issues)."""


@dataclass
class CarveMeDefaults:
    solver: str | None = None
    universe: str | None = None
    universe_file: str | None = None
    env: str | None = None
    gapfill_media: str | None = None
    init_medium: str | None = None
    timeout: int | None = None
    max_parallel: int | None = None


@dataclass
class ModelInput:
    """An existing SBML model fed into the pipeline (instead of building one)."""

    path: Path
    kegg_code: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.label:
            self.label = self.path.stem


@dataclass
class BuildStep:
    mode: str = "batch"  # single | batch
    jobs: list[dict] = field(default_factory=list)
    output_dir: str = "built_models"


@dataclass
class RefineStep:
    enabled: bool = False
    universal: str = ""
    tasks: str = ""
    medium: str | None = None
    skip_evaluation: bool = False
    include_exchange_gapfill: bool = False
    output_model: str = ""
    output_report: str = ""


@dataclass
class PipelineSpec:
    carveme: CarveMeDefaults = field(default_factory=CarveMeDefaults)
    build: BuildStep | None = None
    models: list[ModelInput] = field(default_factory=list)
    refine: RefineStep = field(default_factory=RefineStep)


@dataclass
class PipelineResult:
    # Count of models successfully resolved — whether newly built by CarveMe or
    # loaded from an existing SBML (the `models:` list). Used as the "did any
    # model make it through resolution" guard, so it must include loaded models.
    models_built: int = 0
    models_failed: int = 0
    models_refined: int = 0
    labels: list[str] = field(default_factory=list)


# -- parsing / validation ---------------------------------------------------


def load_pipeline(path: str | Path) -> PipelineSpec:
    """Parse and validate a pipeline YAML. Raises PipelineError listing all issues."""
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency present in env
        raise PipelineError(
            "PyYAML is required for --config. Install it: pip install pyyaml"
        ) from exc

    path = Path(path)
    if not path.exists():
        raise PipelineError(f"Config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise PipelineError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PipelineError(f"Pipeline config {path} must be a mapping at the top level")

    errors: list[str] = []
    spec = _build_spec(raw, errors)
    if errors:
        raise PipelineError(
            "Pipeline config invalid:\n  " + "\n  ".join(errors)
        )
    return spec


def _as_section(raw: dict, key: str, errors: list[str]) -> dict:
    """Return a mapping section, or {} (with a recorded error) if it isn't one."""
    val = raw.get(key)
    if val is None:
        return {}
    if not isinstance(val, dict):
        errors.append(f"'{key}' must be a mapping")
        return {}
    return val


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _build_spec(raw: dict, errors: list[str]) -> PipelineSpec:
    carveme = _parse_carveme(_as_section(raw, "carveme", errors), errors)

    has_build = bool(raw.get("build"))
    has_models = bool(raw.get("models"))
    if has_build == has_models:
        errors.append("specify exactly one of 'build' or 'models'")

    build = _parse_build(raw.get("build"), errors) if has_build else None
    models = _parse_models(raw.get("models"), errors) if has_models else []
    refine = _parse_refine(_as_section(raw, "refine", errors), errors)

    return PipelineSpec(
        carveme=carveme, build=build, models=models, refine=refine
    )


def _parse_carveme(cm: dict, errors: list[str]) -> CarveMeDefaults:
    solver = cm.get("solver")
    if solver and solver not in _VALID_SOLVERS:
        errors.append(f"carveme.solver must be one of {_VALID_SOLVERS}, got '{solver}'")
    universe = cm.get("universe")
    if universe and universe not in VALID_UNIVERSES:
        # Soft warning (mirrors build_manifest): carve accepts custom universes.
        logger.warning(
            "carveme.universe '%s' is not a standard template %s; passing through",
            universe, VALID_UNIVERSES[1:],
        )
    timeout = cm.get("timeout")
    if timeout is not None and not _is_int(timeout):
        errors.append(f"carveme.timeout must be an integer, got {timeout!r}")
        timeout = None
    max_parallel = cm.get("max_parallel")
    if max_parallel is not None and not _is_int(max_parallel):
        errors.append(f"carveme.max_parallel must be an integer, got {max_parallel!r}")
        max_parallel = None
    universe_file = cm.get("universe_file")
    if universe_file and not Path(universe_file).exists():
        errors.append(f"carveme.universe_file not found: {universe_file}")
    return CarveMeDefaults(
        solver=solver,
        universe=universe,
        universe_file=universe_file,
        env=cm.get("env"),
        gapfill_media=cm.get("gapfill_media"),
        init_medium=cm.get("init_medium"),
        timeout=timeout,
        max_parallel=max_parallel,
    )


def _parse_build(b: Any, errors: list[str]) -> BuildStep:
    if not isinstance(b, dict):
        errors.append("'build' must be a mapping")
        return BuildStep()
    mode = str(b.get("mode") or "batch").lower()
    if mode not in ("single", "batch"):
        errors.append(f"build.mode must be 'single' or 'batch', got '{mode}'")
    jobs = b.get("jobs") or []
    if not isinstance(jobs, list) or not jobs:
        errors.append("build.jobs must be a non-empty list")
        jobs = []
    if mode == "single" and len(jobs) != 1:
        errors.append("build.mode=single requires exactly one job")
    for i, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            errors.append(f"build.jobs[{i}] must be a mapping")
            continue
        fasta = job.get("fasta")
        if not fasta:
            errors.append(f"build.jobs[{i}]: missing 'fasta'")
        elif not Path(fasta).exists():
            errors.append(f"build.jobs[{i}]: fasta not found: {fasta}")
        if not job.get("kegg_code"):
            errors.append(f"build.jobs[{i}]: missing 'kegg_code' (KEGG taxonomy code)")
        job_universe_file = job.get("universe_file")
        if job_universe_file and not Path(job_universe_file).exists():
            errors.append(f"build.jobs[{i}]: universe_file not found: {job_universe_file}")
    return BuildStep(mode=mode, jobs=jobs, output_dir=str(b.get("output_dir", "built_models")))


def _parse_models(models: Any, errors: list[str]) -> list[ModelInput]:
    if not isinstance(models, list) or not models:
        errors.append("'models' must be a non-empty list")
        return []
    parsed: list[ModelInput] = []
    for i, m in enumerate(models, start=1):
        if not isinstance(m, dict):
            errors.append(f"models[{i}] must be a mapping")
            continue
        p = m.get("path")
        if not p:
            errors.append(f"models[{i}]: missing 'path'")
            continue
        if not Path(p).exists():
            errors.append(f"models[{i}]: model not found: {p}")
        parsed.append(
            ModelInput(path=Path(p), kegg_code=m.get("kegg_code"), label=m.get("label", ""))
        )
    return parsed


def _parse_refine(r: dict, errors: list[str]) -> RefineStep:
    refine = RefineStep(
        enabled=bool(r.get("enabled")),
        universal=str(r.get("universal", "")),
        tasks=str(r.get("tasks", "")),
        medium=r.get("medium"),
        skip_evaluation=bool(r.get("skip_evaluation")),
        include_exchange_gapfill=bool(r.get("include_exchange_gapfill")),
        output_model=str(r.get("output_model", "")),
        output_report=str(r.get("output_report", "")),
    )
    if refine.enabled:
        if not refine.universal or not Path(refine.universal).exists():
            errors.append(f"refine.universal not found: {refine.universal or '(missing)'}")
        if not refine.tasks or not Path(refine.tasks).exists():
            errors.append(f"refine.tasks not found: {refine.tasks or '(missing)'}")
    return refine


# -- execution --------------------------------------------------------------


def apply_carveme_defaults(
    config: Config,
    cm: CarveMeDefaults,
    cli_overridden: set[str] | None = None,
) -> None:
    """Layer the YAML carveme defaults onto the config for this run.

    Fields named in ``cli_overridden`` were set explicitly on the command line
    and are left untouched, so CLI flags win over the YAML ``carveme:`` block.
    """
    overridden = cli_overridden or set()
    if cm.solver and "carveme_solver" not in overridden:
        config.carveme_solver = cm.solver
    if cm.universe is not None and "carveme_universe" not in overridden:
        config.carveme_universe = cm.universe
    if cm.universe_file is not None and "carveme_universe_file" not in overridden:
        config.carveme_universe_file = cm.universe_file
    if cm.env is not None and "carveme_env" not in overridden:
        config.carveme_env = cm.env
    if cm.gapfill_media is not None and "carveme_gapfill_media" not in overridden:
        config.carveme_gapfill_media = cm.gapfill_media
    if cm.init_medium is not None and "carveme_init_medium" not in overridden:
        config.carveme_init_medium = cm.init_medium
    if cm.timeout is not None and "carveme_timeout" not in overridden:
        config.carveme_timeout = int(cm.timeout)
    if cm.max_parallel is not None and "carveme_max_parallel" not in overridden:
        config.carveme_max_parallel = int(cm.max_parallel)


def _fmt(template: str, label: str, model_id: str) -> str:
    return template.replace("{label}", label).replace("{model}", model_id)


async def run_pipeline(
    spec: PipelineSpec,
    config: Config,
    log: LogCallback | None = None,
    cli_overridden: set[str] | None = None,
) -> PipelineResult:
    """Execute a validated pipeline: resolve models, then refine + evaluate each.

    ``cli_overridden`` names CarveMe config fields set explicitly on the command
    line; those keep precedence over the YAML ``carveme:`` block (CLI > YAML >
    built-in defaults).
    """
    _log = log or logger.info
    apply_carveme_defaults(config, spec.carveme, cli_overridden)

    result = PipelineResult()
    models = _dedupe_labels(_resolve_models(spec, config, _log, result), _log)
    _check_output_collisions(spec, models)  # raises PipelineError on collision

    # Baseline organism to reset to for any model without its own KEGG code,
    # so a previous model's organism never leaks into the next.
    base_org = (config.kegg_organism_code, config.organism_name)

    for label, kegg, model_data in models:
        result.labels.append(label)
        code = kegg or getattr(model_data, "kegg_organism_code", None)
        if code:
            config.kegg_organism_code = code
            config.organism_name = KEGG_CODE_TO_NAME.get(
                code, getattr(model_data, "organism", None) or code
            )
        else:
            config.kegg_organism_code, config.organism_name = base_org

        try:
            if spec.refine.enabled:
                await _run_refine(spec.refine, config, label, model_data, _log)
                result.models_refined += 1
        except Exception as exc:  # noqa: BLE001 - one model's failure must not abort the run
            result.models_failed += 1
            _log(f"[ERROR] model '{label}' failed: {exc}")
            logger.exception("Pipeline model '%s' failed", label)

    _log(
        f"Pipeline complete: {result.models_built} resolved, "
        f"{result.models_failed} failed, {result.models_refined} refined"
    )
    return result


def _dedupe_labels(
    models: list[tuple[str, str | None, Any]], log: LogCallback
) -> list[tuple[str, str | None, Any]]:
    """Ensure labels are unique so {label}-templated outputs never collide."""
    seen: set[str] = set()
    out: list[tuple[str, str | None, Any]] = []
    for label, kegg, md in models:
        new = label
        n = 2
        while new in seen:
            new = f"{label}_{n}"
            n += 1
        if new != label:
            log(f"[WARN] duplicate label '{label}' -> '{new}'")
        seen.add(new)
        out.append((new, kegg, md))
    return out


def _check_output_collisions(spec: PipelineSpec, models: list[tuple[str, str | None, Any]]) -> None:
    """Raise PipelineError if two models resolve to the same output file."""
    used: dict[str, str] = {}
    collisions: list[str] = []

    def _add(path: str, label: str) -> None:
        if not path:
            return
        if path in used and used[path] != label:
            collisions.append(f"{path} (models '{used[path]}' and '{label}')")
        used[path] = label

    for label, _kegg, md in models:
        if spec.refine.enabled:
            if spec.refine.output_model:
                _add(_fmt(spec.refine.output_model, label, md.id), label)
            if spec.refine.output_report:
                _add(_fmt(spec.refine.output_report, label, md.id), label)

    if collisions:
        raise PipelineError(
            "Output path collision(s) — add unique 'label:' values or use "
            "{label}/{model} in the output templates:\n  " + "\n  ".join(collisions)
        )


def _resolve_models(
    spec: PipelineSpec,
    config: Config,
    log: LogCallback,
    result: PipelineResult,
) -> list[tuple[str, str | None, Any]]:
    if spec.build is not None:
        return _resolve_built_models(spec.build, config, log, result)
    return _resolve_existing_models(spec.models, log, result)


def _resolve_built_models(
    build: BuildStep, config: Config, log: LogCallback, result: PipelineResult
) -> list[tuple[str, str | None, Any]]:
    from src.build.build_engine import BuildEngine
    from src.build.build_manifest import BuildJob

    engine = BuildEngine(config)
    avail = engine.runner.check_available(solver=config.carveme_solver)
    if not avail.ok:
        raise PipelineError("CarveMe toolchain not available:\n" + avail.message)
    log(avail.message)

    jobs = [
        BuildJob(
            fasta_path=Path(j["fasta"]),
            kegg_code=j.get("kegg_code", ""),
            universe=j.get("universe", ""),
            universe_file=j.get("universe_file", ""),
            gram=j.get("gram", ""),
            medium=j.get("medium", ""),
            label=j.get("label", ""),
        )
        for j in build.jobs
    ]
    log(f"Building {len(jobs)} model(s) (mode={build.mode}) -> {build.output_dir}")

    items = engine.build_batch(
        jobs,
        output_dir=build.output_dir,
        on_line=lambda line: log("  " + line),
    )
    models: list[tuple[str, str | None, Any]] = []
    for item in items:
        if item.built is not None:
            md = item.built.model_data
            result.models_built += 1
            log(f"[OK] {item.job.label}: {md.id} ({md.reaction_count} rxn)")
            models.append((item.job.label, item.job.kegg_code, md))
        else:
            result.models_failed += 1
            log(f"[FAIL] {item.job.label}: {item.error}")
    return models


def _resolve_existing_models(
    inputs: list[ModelInput], log: LogCallback, result: PipelineResult
) -> list[tuple[str, str | None, Any]]:
    from src.core.sbml_parser import SBMLParser

    models: list[tuple[str, str | None, Any]] = []
    for inp in inputs:
        try:
            md = SBMLParser().load_model(inp.path)
        except Exception as exc:  # noqa: BLE001 - one bad model must not abort the run
            result.models_failed += 1
            log(f"[FAIL] {inp.label}: load failed: {exc}")
            continue
        if inp.kegg_code:
            md.kegg_organism_code = inp.kegg_code
            md.organism = KEGG_CODE_TO_NAME.get(inp.kegg_code, md.organism or inp.kegg_code)
        result.models_built += 1
        log(f"[LOADED] {inp.label}: {md.id} ({md.reaction_count} rxn)")
        models.append((inp.label, inp.kegg_code, md))
    return models


async def _run_refine(
    refine: RefineStep, config: Config, label: str, model_data: Any, log: LogCallback
) -> None:
    # Organism is already set on config per-model by run_pipeline.
    from src.cli import async_gapfill_main

    out_model = _fmt(refine.output_model, label, model_data.id) if refine.output_model else None
    out_report = _fmt(refine.output_report, label, model_data.id) if refine.output_report else None
    for out in (out_model, out_report):
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)

    log(f"== Refine '{label}' (organism={config.kegg_organism_code or 'generic'}) ==")
    await async_gapfill_main(
        config=config,
        model_data=model_data,
        universal_path=refine.universal,
        tasks_path=refine.tasks,
        medium_arg=refine.medium,
        output_model=out_model,
        output_report=out_report,
        skip_evaluation=refine.skip_evaluation,
        include_exchange_gapfill=refine.include_exchange_gapfill,
    )


