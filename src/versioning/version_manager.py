"""Version management orchestrator."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import cobra

from src.core.models import ModelDiff, ModelVersion, TaskResult
from src.utils.config import Config
from src.versioning.change_summarizer import ChangeSummarizer
from src.versioning.diff_engine import DiffEngine
from src.versioning.storage import VersionStorage

logger = logging.getLogger("gem_evaluator.versioning.version_manager")


class VersionManager:
    """Orchestrate model version saving, comparison, and restoration."""

    def __init__(self, config: Config) -> None:
        self._config = config
        base_dir = Path(config.version_dir) if config.version_dir else None
        self._storage = VersionStorage(base_dir=base_dir)
        self._diff_engine = DiffEngine()
        self._summarizer = ChangeSummarizer(config)
        self._current_version: ModelVersion | None = None
        self._previous_model: cobra.Model | None = None
        self._model_id: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_base_model(self, cobra_model: cobra.Model, model_id: str) -> None:
        """Save the initial model load as v001.

        Called once when a model is first loaded.
        """
        self._model_id = model_id

        # Build a diff that captures the full model as "added"
        empty = cobra.Model("empty")
        diff = self._diff_engine.compute_diff(empty, cobra_model)

        version_id = self._storage.get_next_version_id(model_id)
        version = ModelVersion(
            version_id=version_id,
            timestamp=self._now(),
            parent_version_id=None,
            model_id=model_id,
            description=self._summarizer._template_summary(diff, "initial_load"),
            change_type="initial_load",
            diff=diff,
        )

        self._storage.save_version(model_id, version, cobra_model)
        self._current_version = version
        self._previous_model = cobra_model.copy()

        logger.info("Base model set: %s as %s", model_id, version_id)

    async def save_version(
        self,
        cobra_model: cobra.Model,
        change_type: str,
        task_results: list[TaskResult] | None = None,
        custom_description: str | None = None,
    ) -> ModelVersion:
        """Save a new version snapshot.

        Steps:
            1. Compute diff against previous model.
            2. Generate description (custom or via ChangeSummarizer).
            3. Compute task_pass_rate from task_results if provided.
            4. Persist via VersionStorage.
            5. Cleanup old versions if over limit.
            6. Update internal state.

        Returns:
            The newly created ModelVersion.
        """
        if self._previous_model is None:
            raise RuntimeError(
                "No base model set. Call set_base_model() first."
            )

        diff = self._diff_engine.compute_diff(self._previous_model, cobra_model)

        if custom_description:
            description = custom_description
        else:
            description = await self._summarizer.summarize(diff, change_type)

        pass_rate: str | None = None
        if task_results:
            passed = sum(1 for r in task_results if r.passed)
            pass_rate = f"{passed}/{len(task_results)}"

        version_id = self._storage.get_next_version_id(self._model_id)
        parent_id = self._current_version.version_id if self._current_version else None

        version = ModelVersion(
            version_id=version_id,
            timestamp=self._now(),
            parent_version_id=parent_id,
            model_id=self._model_id,
            description=description,
            change_type=change_type,
            diff=diff,
            task_pass_rate=pass_rate,
        )

        self._storage.save_version(self._model_id, version, cobra_model)

        # Cleanup if over limit
        max_versions = self._config.max_versions
        deleted = self._storage.cleanup_old_versions(self._model_id, max_versions)
        if deleted:
            logger.info("Cleaned up %d old versions", deleted)

        self._current_version = version
        self._previous_model = cobra_model.copy()

        logger.info("Saved version %s (%s)", version_id, change_type)
        return version

    def restore_version(self, version_id: str) -> cobra.Model:
        """Restore a specific version.

        Loads the target version and saves a new "restore" version
        so the history records the restoration event.

        Returns:
            The restored cobra.Model.
        """
        model, _meta = self._storage.load_version(self._model_id, version_id)

        # Compute diff from current to restored
        if self._previous_model is not None:
            diff = self._diff_engine.compute_diff(self._previous_model, model)
        else:
            diff = ModelDiff()

        new_version_id = self._storage.get_next_version_id(self._model_id)
        parent_id = self._current_version.version_id if self._current_version else None

        description = f"Restored to version {version_id}"
        version = ModelVersion(
            version_id=new_version_id,
            timestamp=self._now(),
            parent_version_id=parent_id,
            model_id=self._model_id,
            description=description,
            change_type="restore",
            diff=diff,
        )

        self._storage.save_version(self._model_id, version, model)
        self._current_version = version
        self._previous_model = model.copy()

        logger.info("Restored version %s as %s", version_id, new_version_id)
        return model

    def get_history(self) -> list[ModelVersion]:
        """Return the full version history for the current model."""
        return self._storage.load_history(self._model_id)

    def compare_versions(
        self, version_a: str, version_b: str
    ) -> ModelDiff:
        """Compare two versions by loading and diffing their models."""
        model_a, _ = self._storage.load_version(self._model_id, version_a)
        model_b, _ = self._storage.load_version(self._model_id, version_b)
        return self._diff_engine.compute_diff(model_a, model_b)

    @property
    def current_version(self) -> ModelVersion | None:
        """The most recently saved version."""
        return self._current_version

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=timezone.utc).isoformat()
