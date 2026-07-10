"""Subprocess wrapper around the CarveMe ``carve`` CLI.

CarveMe is invoked as an external process so its ``reframed``/``python-libsbml``
dependencies never need to be imported into the app process. This module is
GUI- and cobra-agnostic: it only knows how to run ``carve``, stream its output,
support cancellation/timeout, and report whether the toolchain is installed.

``carve`` flags used (from ``carve --help``):
    carve INPUT -o OUTPUT [--solver gurobi] [-u UNIVERSE] [-g MEDIA] [-i MEDIUM] [-v]

Note: carve's built-in default solver is ``cplex``. We always pass ``--solver``
explicitly (default ``gurobi``) so a build never silently fails on a missing
CPLEX license.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("metataskgapfill.build.carveme")

# carve --solver argument -> python module to probe for availability.
_SOLVER_IMPORT = {"gurobi": "gurobipy", "cplex": "cplex", "scip": "pyscipopt"}

# Universe templates carve ships with (used for soft validation only; carve
# also accepts arbitrary names via its own bundled data).
VALID_UNIVERSES = ("", "bacteria", "grampos", "gramneg", "archaea", "cyanobacteria")

_TAIL_LINES = 300
_POLL_INTERVAL = 0.2


class _CancelToken(Protocol):
    """Minimal cancellation contract (threading.Event satisfies this)."""

    def is_set(self) -> bool: ...


class CarveMeError(RuntimeError):
    """Base class for CarveMe runner failures."""


class CarveMeNotInstalledError(CarveMeError):
    """Raised when the ``carve`` binary (or its env) cannot be found."""


class CarveMeRunError(CarveMeError):
    """Raised when a ``carve`` invocation fails, is cancelled, or times out."""


@dataclass(frozen=True)
class CarveMeOptions:
    """Options passed to a single ``carve`` invocation."""

    solver: str = "gurobi"  # --solver (gurobi|cplex|scip); "" = carve default
    universe: str = ""  # -u (bacteria|grampos|gramneg|archaea|...); "" = default
    universe_file: str = ""  # --universe-file (custom SBML universe)
    gapfill_media: str = ""  # -g (carve's own gap-fill, e.g. "M9,LB")
    init_medium: str = ""  # -i (e.g. "M9")
    dna: bool = False  # --dna (INPUT is a nucleotide fasta)
    gzip_output: bool = False  # write .xml.gz (carve infers from -o suffix)
    verbose: bool = True  # -v (stream progress)
    timeout: int = 1800  # seconds per model
    extra_args: tuple[str, ...] = ()

    def output_suffix(self) -> str:
        return ".xml.gz" if self.gzip_output else ".xml"


@dataclass
class CarveMeResult:
    """Outcome of one ``carve`` build."""

    fasta_path: Path
    output_path: Path
    returncode: int = -1
    duration_s: float = 0.0
    stdout_tail: str = ""
    cancelled: bool = False
    error: str | None = None
    kegg_code: str | None = None  # carried through for the downstream evaluator
    label: str = ""
    argv: list[str] = field(default_factory=list)
    options: CarveMeOptions | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.returncode == 0
            and not self.cancelled
            and self.error is None
            and self.output_path.exists()
        )


@dataclass
class CarveMeAvailability:
    """Result of probing the local CarveMe toolchain."""

    carve_ok: bool = False
    diamond_ok: bool = False
    solver_ok: bool | None = None
    carve_path: str = ""
    carve_version: str = "unknown"
    diamond_version: str = "unknown"
    solver_name: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        # A build needs carve + diamond. Solver availability is advisory
        # (carve itself raises a clear error if the solver is missing).
        return self.carve_ok and self.diamond_ok


@dataclass
class BuildSpec:
    """A single resolved build: which fasta, where to write, with what options."""

    fasta_path: Path
    output_path: Path
    options: CarveMeOptions
    kegg_code: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        self.fasta_path = Path(self.fasta_path)
        self.output_path = Path(self.output_path)
        if not self.label:
            self.label = self.fasta_path.stem


def install_hint(conda_env: str = "") -> str:
    """Human-readable remediation for a missing CarveMe toolchain."""
    lines = [
        "CarveMe toolchain not found. Install it with:",
        "  pip install carveme gurobipy",
        "  conda install -c bioconda diamond",
        "and ensure a MILP solver is available (Gurobi/CPLEX licensed, or SCIP).",
    ]
    if conda_env:
        lines.append(
            f"Configured CarveMe conda env is '{conda_env}'; verify it exists "
            f"and contains `carve` (conda run -n {conda_env} carve --help)."
        )
    return "\n".join(lines)


class CarveMeRunner:
    """Run the ``carve`` CLI as a subprocess with streaming + cancel + timeout."""

    def __init__(
        self,
        executable: str = "carve",
        conda_env: str = "",
        diamond_executable: str = "diamond",
    ) -> None:
        self._executable = executable or "carve"
        self._conda_env = (conda_env or "").strip()
        self._diamond = diamond_executable or "diamond"
        self._last_availability: CarveMeAvailability | None = None

    @property
    def last_availability(self) -> CarveMeAvailability | None:
        return self._last_availability

    # -- command resolution -------------------------------------------------

    def _conda_prefix(self) -> list[str]:
        """Prefix that runs a command inside the configured conda env, if any."""
        if not self._conda_env:
            return []
        conda = shutil.which("conda")
        if not conda:
            # Best-effort fallbacks for common anaconda layouts.
            for cand in (
                Path(sys.prefix).parent.parent / "bin" / "conda",
                Path.home() / "anaconda3" / "bin" / "conda",
                Path.home() / "miniconda3" / "bin" / "conda",
            ):
                if cand.exists():
                    conda = str(cand)
                    break
        if not conda:
            raise CarveMeNotInstalledError(
                f"conda env '{self._conda_env}' configured but `conda` not found on PATH.\n"
                + install_hint(self._conda_env)
            )
        return [conda, "run", "--no-capture-output", "-n", self._conda_env]

    def carve_cmd(self) -> list[str]:
        return self._conda_prefix() + [self._executable]

    def diamond_cmd(self) -> list[str]:
        return self._conda_prefix() + [self._diamond]

    def python_cmd(self) -> list[str]:
        if self._conda_env:
            return self._conda_prefix() + ["python"]
        return [sys.executable]

    # -- availability -------------------------------------------------------

    def check_available(self, solver: str | None = None) -> CarveMeAvailability:
        """Probe carve, diamond, and (advisory) the requested MILP solver."""
        avail = CarveMeAvailability()
        self._last_availability = avail

        # carve (validates the conda env exists, if configured)
        try:
            self._conda_prefix()
        except CarveMeNotInstalledError as exc:
            avail.message = str(exc)
            return avail
        if not self._conda_env:
            resolved = shutil.which(self._executable)
            avail.carve_path = resolved or ""
            if not resolved:
                avail.message = install_hint(self._conda_env)
                return avail
        try:
            help_proc = subprocess.run(
                self.carve_cmd() + ["--help"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            avail.carve_ok = help_proc.returncode == 0
            if avail.carve_ok and self._conda_env:
                avail.carve_path = f"conda:{self._conda_env}:{self._executable}"
        except Exception as exc:  # noqa: BLE001 - report any probe failure
            avail.message = f"`carve --help` failed: {exc}\n" + install_hint(self._conda_env)
            return avail

        # carve version (best effort)
        try:
            ver = subprocess.run(
                self.python_cmd() + ["-c", "import carveme; print(carveme.__version__)"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if ver.returncode == 0 and ver.stdout.strip():
                avail.carve_version = ver.stdout.strip()
        except Exception:  # noqa: BLE001
            pass

        # diamond
        try:
            dproc = subprocess.run(
                self.diamond_cmd() + ["--version"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            avail.diamond_ok = dproc.returncode == 0
            if avail.diamond_ok:
                avail.diamond_version = (
                    (dproc.stdout or dproc.stderr).strip().splitlines()[0]
                    if (dproc.stdout or dproc.stderr).strip()
                    else "unknown"
                )
        except Exception:  # noqa: BLE001
            avail.diamond_ok = False

        # solver (advisory)
        solver = (solver or "").strip().lower()
        if solver and solver in _SOLVER_IMPORT:
            avail.solver_name = solver
            mod = _SOLVER_IMPORT[solver]
            try:
                sproc = subprocess.run(
                    self.python_cmd() + ["-c", f"import {mod}"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                avail.solver_ok = sproc.returncode == 0
            except Exception:  # noqa: BLE001
                avail.solver_ok = False

        parts = [
            f"carve: {'OK' if avail.carve_ok else 'MISSING'} ({avail.carve_version})",
            f"diamond: {'OK' if avail.diamond_ok else 'MISSING'} ({avail.diamond_version})",
        ]
        if avail.solver_name:
            parts.append(
                f"solver {avail.solver_name}: " + ("OK" if avail.solver_ok else "not importable")
            )
        avail.message = "; ".join(parts)
        if not avail.ok:
            avail.message += "\n" + install_hint(self._conda_env)
        return avail

    # -- argv construction --------------------------------------------------

    def build_argv(self, spec: BuildSpec) -> list[str]:
        """Assemble the full ``carve`` argv for a build spec (no shell)."""
        opts = spec.options
        argv = self.carve_cmd() + [str(spec.fasta_path), "-o", str(spec.output_path)]
        if opts.dna:
            argv.append("--dna")
        if opts.solver:
            argv += ["--solver", opts.solver]
        if opts.universe_file:
            argv += ["--universe-file", opts.universe_file]
        elif opts.universe:
            argv += ["--universe", opts.universe]
        if opts.gapfill_media:
            argv += ["--gapfill", opts.gapfill_media]
        if opts.init_medium:
            argv += ["--init", opts.init_medium]
        if opts.verbose:
            argv.append("-v")
        argv += list(opts.extra_args)
        return argv

    # -- single build -------------------------------------------------------

    def build_single(
        self,
        fasta_path: str | Path,
        output_path: str | Path,
        options: CarveMeOptions | None = None,
        on_line: Callable[[str], None] | None = None,
        cancel_token: _CancelToken | None = None,
        kegg_code: str | None = None,
        label: str = "",
    ) -> CarveMeResult:
        """Build one model from a protein FASTA. Raises CarveMeRunError on failure."""
        options = options or CarveMeOptions()
        fasta_path = Path(fasta_path)
        output_path = Path(output_path)
        spec = BuildSpec(fasta_path, output_path, options, kegg_code=kegg_code, label=label)

        if not fasta_path.exists():
            raise CarveMeRunError(f"FASTA file not found: {fasta_path}")
        if options.universe_file and not Path(options.universe_file).exists():
            raise CarveMeRunError(f"Universe file not found: {options.universe_file}")
        if not self._conda_env and shutil.which(self._executable) is None:
            raise CarveMeNotInstalledError(install_hint(self._conda_env))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        argv = self.build_argv(spec)
        logger.info("Running carve: %s", " ".join(argv))
        start = time.monotonic()
        returncode, tail, cancelled = self._run_streaming(
            argv, options.timeout, on_line, cancel_token
        )
        duration = time.monotonic() - start
        result = CarveMeResult(
            fasta_path=fasta_path,
            output_path=output_path,
            returncode=returncode,
            duration_s=duration,
            stdout_tail=tail,
            cancelled=cancelled,
            kegg_code=kegg_code,
            label=spec.label,
            argv=list(argv),
            options=options,
        )
        if cancelled:
            result.error = "cancelled"
            raise CarveMeRunError(f"carve build cancelled for {fasta_path.name}")
        if returncode != 0:
            result.error = f"carve exited with code {returncode}"
            raise CarveMeRunError(
                f"carve failed for {fasta_path.name} (exit {returncode}).\nLast output:\n{tail}"
            )
        if not output_path.exists():
            result.error = "no output produced"
            raise CarveMeRunError(
                f"carve reported success but produced no model at {output_path}.\n"
                f"Last output:\n{tail}"
            )
        logger.info("carve produced %s in %.1fs", output_path, duration)
        return result

    # -- batch build --------------------------------------------------------

    def build_batch(
        self,
        specs: Sequence[BuildSpec],
        on_line: Callable[[str], None] | None = None,
        on_item_start: Callable[[int, BuildSpec], None] | None = None,
        on_item_done: Callable[[int, CarveMeResult], None] | None = None,
        cancel_token: _CancelToken | None = None,
        max_parallel: int = 1,
    ) -> list[CarveMeResult]:
        """Build several models. A failure in one model does not abort the rest.

        Returns one CarveMeResult per spec (in input order); failed/cancelled
        builds carry ``error``/``cancelled`` instead of raising.
        """
        specs = list(specs)
        results: list[CarveMeResult] = [None] * len(specs)  # type: ignore[list-item]
        max_parallel = max(1, int(max_parallel))

        def _run_one(index: int, spec: BuildSpec) -> CarveMeResult:
            if cancel_token is not None and cancel_token.is_set():
                return CarveMeResult(
                    fasta_path=spec.fasta_path,
                    output_path=spec.output_path,
                    cancelled=True,
                    error="cancelled",
                    kegg_code=spec.kegg_code,
                    label=spec.label,
                    argv=self.build_argv(spec),
                    options=spec.options,
                )
            if on_item_start is not None:
                on_item_start(index, spec)

            def _line(line: str) -> None:
                if on_line is not None:
                    on_line(f"[{spec.label}] {line}")

            try:
                return self.build_single(
                    spec.fasta_path,
                    spec.output_path,
                    spec.options,
                    on_line=_line,
                    cancel_token=cancel_token,
                    kegg_code=spec.kegg_code,
                    label=spec.label,
                )
            except Exception as exc:  # noqa: BLE001 - one model's failure must not abort the batch
                logger.warning("Batch model '%s' failed: %s", spec.label, exc)
                return CarveMeResult(
                    fasta_path=spec.fasta_path,
                    output_path=spec.output_path,
                    cancelled="cancelled" in str(exc).lower(),
                    error=str(exc),
                    kegg_code=spec.kegg_code,
                    label=spec.label,
                    argv=self.build_argv(spec),
                    options=spec.options,
                )

        if max_parallel == 1:
            for index, spec in enumerate(specs):
                res = _run_one(index, spec)
                results[index] = res
                if on_item_done is not None:
                    on_item_done(index, res)
        else:
            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = {
                    pool.submit(_run_one, index, spec): index for index, spec in enumerate(specs)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    res = future.result()
                    results[index] = res
                    if on_item_done is not None:
                        on_item_done(index, res)

        return results

    # -- subprocess plumbing ------------------------------------------------

    def _run_streaming(
        self,
        argv: list[str],
        timeout: int,
        on_line: Callable[[str], None] | None,
        cancel_token: _CancelToken | None,
    ) -> tuple[int, str, bool]:
        """Run argv, streaming stdout/stderr lines; honour cancel + timeout.

        Returns ``(returncode, tail, cancelled)``.
        """
        popen_kwargs: dict = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True  # own process group -> killpg
        else:  # pragma: no cover - Windows
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        proc = subprocess.Popen(argv, **popen_kwargs)
        line_q: queue.Queue[str | None] = queue.Queue()

        def _reader() -> None:
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line_q.put(raw.rstrip("\n"))
            finally:
                line_q.put(None)  # sentinel: stream closed

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        tail: deque[str] = deque(maxlen=_TAIL_LINES)
        start = time.monotonic()
        cancelled = False
        stream_done = False

        while True:
            if cancel_token is not None and cancel_token.is_set():
                cancelled = True
                self._terminate(proc)
                break
            if timeout and (time.monotonic() - start) > timeout:
                self._terminate(proc)
                tail.append(f"[runner] timed out after {timeout}s")
                if on_line is not None:
                    on_line(f"[runner] timed out after {timeout}s")
                break
            try:
                item = line_q.get(timeout=_POLL_INTERVAL)
            except queue.Empty:
                if proc.poll() is not None and stream_done:
                    break
                continue
            if item is None:
                stream_done = True
                if proc.poll() is not None:
                    break
                continue
            tail.append(item)
            if on_line is not None:
                on_line(item)

        if cancelled or (timeout and (time.monotonic() - start) > timeout):
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
            returncode = proc.returncode if proc.returncode is not None else -1
        else:
            returncode = proc.wait()
        # Force the reader out of a blocked `for raw in proc.stdout` in case a
        # grandchild escaped the process group and still holds the write-end.
        with contextlib.suppress(Exception):
            if proc.stdout is not None:
                proc.stdout.close()
        reader.join(timeout=2)
        return returncode, "\n".join(tail), cancelled

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """Terminate the process (group), escalating to SIGKILL if needed."""
        if proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:  # pragma: no cover - Windows
                proc.terminate()
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):
                proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)
            return
        with contextlib.suppress(Exception):
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:  # pragma: no cover - Windows
                proc.kill()


# Re-exported for callers that build specs directly.
__all__ = [
    "CarveMeOptions",
    "CarveMeResult",
    "CarveMeAvailability",
    "CarveMeRunner",
    "BuildSpec",
    "CarveMeError",
    "CarveMeNotInstalledError",
    "CarveMeRunError",
    "VALID_UNIVERSES",
    "install_hint",
]
