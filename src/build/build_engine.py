"""Model construction orchestration: build → load → (optional) refine.

This is the single source of truth used identically by the CLI and the GUI.
It turns protein FASTA files into loaded :class:`~src.core.models.ModelData`
(via CarveMe + :class:`~src.core.sbml_parser.SBMLParser`) and can hand a built
model into the existing task-aware gap-fill pipeline (single model at a time).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from src.build.build_manifest import BuildJob
from src.build.carveme_runner import (
    BuildSpec,
    CarveMeOptions,
    CarveMeResult,
    CarveMeRunner,
)
from src.core.models import GapFillResult, ModelData
from src.core.sbml_parser import SBMLParser
from src.gapfill.refine import RefineOutcome, refine_model_data
from src.utils.config import Config
from src.utils.constants import KEGG_CODE_TO_NAME

logger = logging.getLogger("metataskgapfill.build.engine")

_CancelToken = object  # has .is_set(); kept loose to avoid importing threading here


@dataclass
class BuiltModel:
    """A freshly constructed model loaded into the app's domain format."""

    model_data: ModelData
    sbml_path: Path
    kegg_code: str | None
    carve_result: CarveMeResult

    @property
    def reaction_count(self) -> int:
        return self.model_data.reaction_count


@dataclass
class BuildItemResult:
    """Per-genome outcome of a batch build (success or failure)."""

    job: BuildJob
    carve_result: CarveMeResult
    built: BuiltModel | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.built is not None


class BuildEngine:
    """Build genome-scale models from FASTA and route them to the evaluator."""

    def __init__(self, config: Config, runner: CarveMeRunner | None = None) -> None:
        self._config = config
        self._runner = runner or CarveMeRunner(
            executable=config.carveme_executable,
            conda_env=config.carveme_env,
            diamond_executable=config.carveme_diamond_executable,
        )

    @property
    def runner(self) -> CarveMeRunner:
        return self._runner

    # -- options ------------------------------------------------------------

    def options_from_config(
        self,
        *,
        solver: str | None = None,
        universe: str | None = None,
        universe_file: str | None = None,
        gapfill_media: str | None = None,
        init_medium: str | None = None,
        gzip_output: bool | None = None,
        dna: bool = False,
        timeout: int | None = None,
        extra_args: tuple[str, ...] = (),
    ) -> CarveMeOptions:
        """Build CarveMeOptions from config defaults, applying explicit overrides."""
        cfg = self._config
        return CarveMeOptions(
            solver=cfg.carveme_solver if solver is None else solver,
            universe=cfg.carveme_universe if universe is None else universe,
            universe_file=cfg.carveme_universe_file if universe_file is None else universe_file,
            gapfill_media=cfg.carveme_gapfill_media if gapfill_media is None else gapfill_media,
            init_medium=cfg.carveme_init_medium if init_medium is None else init_medium,
            gzip_output=cfg.carveme_gzip_output if gzip_output is None else gzip_output,
            dna=dna,
            timeout=cfg.carveme_timeout if timeout is None else timeout,
            extra_args=tuple(extra_args),
        )

    # -- single build -------------------------------------------------------

    def build_one(
        self,
        fasta_path: str | Path,
        kegg_code: str | None,
        options: CarveMeOptions | None = None,
        output_path: str | Path | None = None,
        on_line: Callable[[str], None] | None = None,
        cancel_token=None,
        label: str = "",
    ) -> BuiltModel:
        """Build one model and load it. Raises CarveMeRunError on build failure."""
        options = options or self.options_from_config()
        fasta_path = Path(fasta_path)
        if output_path is None:
            output_path = Path(self._config.carveme_output_dir) / (
                fasta_path.stem + options.output_suffix()
            )
        output_path = Path(output_path)

        carve_result = self._runner.build_single(
            fasta_path,
            output_path,
            options,
            on_line=on_line,
            cancel_token=cancel_token,
            kegg_code=kegg_code,
            label=label or fasta_path.stem,
        )
        model_data = self._load_built(carve_result.output_path, kegg_code)
        return BuiltModel(
            model_data=model_data,
            sbml_path=carve_result.output_path,
            kegg_code=kegg_code,
            carve_result=carve_result,
        )

    # -- batch build --------------------------------------------------------

    def build_batch(
        self,
        jobs: list[BuildJob],
        *,
        options: CarveMeOptions | None = None,
        output_dir: str | Path | None = None,
        on_line: Callable[[str], None] | None = None,
        on_model_built: Callable[[int, BuildItemResult], None] | None = None,
        cancel_token=None,
    ) -> list[BuildItemResult]:
        """Build many models (single model at a time, optionally parallel).

        Refinement is NOT performed here — it runs one model at a time and is a
        separate, explicit step (see :meth:`refine`). A failed model does not
        abort the batch; each job yields a BuildItemResult.
        """
        output_dir = Path(output_dir or self._config.carveme_output_dir)
        base_options = options or self.options_from_config()

        # Build specs, guaranteeing unique output paths: two FASTAs sharing a
        # stem (e.g. dirA/eco.faa, dirB/eco.faa) must not overwrite each other.
        specs: list[BuildSpec] = []
        used: set[str] = set()
        for job in jobs:
            spec = self._spec_for_job(job, output_dir, base_options)
            suffix = spec.options.output_suffix()
            base = spec.output_path
            stem = base.name[: -len(suffix)] if base.name.endswith(suffix) else base.stem
            n = 2
            while str(spec.output_path) in used:
                spec.output_path = base.with_name(f"{stem}_{n}{suffix}")
                n += 1
            used.add(str(spec.output_path))
            specs.append(spec)

        by_index: dict[int, BuildItemResult] = {}

        def _on_done(index: int, carve_result: CarveMeResult) -> None:
            item = self._finalize_item(jobs[index], carve_result)
            by_index[index] = item
            if on_model_built is not None:
                on_model_built(index, item)

        self._runner.build_batch(
            specs,
            on_line=on_line,
            on_item_done=_on_done,
            cancel_token=cancel_token,
            max_parallel=self._config.carveme_max_parallel,
        )
        return [by_index[i] for i in range(len(jobs)) if i in by_index]

    # -- refine (single model only) ----------------------------------------

    async def refine(
        self,
        built: BuiltModel,
        *,
        universal_path: str,
        tasks_path: str,
        base_medium: dict[str, float] | None = None,
        skip_evaluation: bool = False,
        include_exchange_gapfill: bool = False,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        log: Callable[[str], None] | None = None,
        evidence_engine=None,
    ) -> RefineOutcome:
        """Run task-aware gap-fill on a single built model (the 고도화 step)."""
        if built.kegg_code:
            self._config.kegg_organism_code = built.kegg_code
            self._config.organism_name = KEGG_CODE_TO_NAME.get(
                built.kegg_code, self._config.organism_name
            )
        return await refine_model_data(
            self._config,
            built.model_data,
            universal_path=universal_path,
            tasks_path=tasks_path,
            base_medium=base_medium,
            skip_evaluation=skip_evaluation,
            include_exchange_gapfill=include_exchange_gapfill,
            progress_callback=progress_callback,
            log=log,
            evidence_engine=evidence_engine,
        )

    # -- helpers ------------------------------------------------------------

    def _spec_for_job(
        self, job: BuildJob, output_dir: Path, base_options: CarveMeOptions
    ) -> BuildSpec:
        # Universe selection is a single choice across two forms (named template
        # vs custom SBML file). A per-job override of EITHER form must beat the
        # inherited global of the OTHER form, otherwise build_argv's
        # universe_file-over-universe rule would silently drop a per-job named
        # universe when a global universe_file is set.
        job_universe = job.resolve_universe()
        if job.universe_file:
            universe, universe_file = "", job.universe_file
        elif job_universe:
            universe, universe_file = job_universe, ""
        else:
            universe, universe_file = base_options.universe, base_options.universe_file
        init_medium = job.medium or base_options.init_medium
        opts = replace(
            base_options, universe=universe, universe_file=universe_file, init_medium=init_medium
        )
        output_path = output_dir / (job.fasta_path.stem + opts.output_suffix())
        return BuildSpec(
            fasta_path=job.fasta_path,
            output_path=output_path,
            options=opts,
            kegg_code=job.kegg_code,
            label=job.label,
        )

    def _finalize_item(self, job: BuildJob, carve_result: CarveMeResult) -> BuildItemResult:
        if not carve_result.succeeded:
            return BuildItemResult(
                job=job,
                carve_result=carve_result,
                built=None,
                error=carve_result.error or "carve build did not succeed",
            )
        try:
            model_data = self._load_built(carve_result.output_path, job.kegg_code)
        except Exception as exc:  # noqa: BLE001 - surface load failures per-item
            logger.error("Failed to load built model %s: %s", carve_result.output_path, exc)
            carve_result.error = f"model load failed: {exc}"
            return BuildItemResult(
                job=job, carve_result=carve_result, built=None, error=str(exc)
            )
        return BuildItemResult(
            job=job,
            carve_result=carve_result,
            built=BuiltModel(
                model_data=model_data,
                sbml_path=carve_result.output_path,
                kegg_code=job.kegg_code,
                carve_result=carve_result,
            ),
        )

    def _load_built(self, sbml_path: Path, kegg_code: str | None) -> ModelData:
        model_data = SBMLParser().load_model(sbml_path)
        self._attach_organism(model_data, kegg_code)
        return model_data

    @staticmethod
    def _attach_organism(model_data: ModelData, kegg_code: str | None) -> None:
        if not kegg_code:
            return
        model_data.kegg_organism_code = kegg_code
        model_data.organism = KEGG_CODE_TO_NAME.get(
            kegg_code, model_data.organism or kegg_code
        )


__all__ = ["BuildEngine", "BuiltModel", "BuildItemResult", "GapFillResult"]
