"""File-system based version storage."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import asdict
from pathlib import Path

import cobra

from src.core.models import ModelDiff, ModelVersion, ReactionChange
from src.utils.constants import VERSION_DIR

logger = logging.getLogger("metataskgapfill.versioning.storage")

_RESTORE_DESC_RE = re.compile(r"\bRestored\s+to\s+version\s+([^\s,;]+)", re.IGNORECASE)


class VersionStorage:
    """Store and load model version snapshots on the file system.

    Directory layout::

        {base_dir}/{model_id}/
            history.json          -- ordered list of ModelVersion metadata
            v001/
                model.xml         -- SBML via cobra.io
                meta.json         -- single ModelVersion as JSON
            v002/
                ...
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or VERSION_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_version(
        self,
        model_id: str,
        version: ModelVersion,
        cobra_model: cobra.Model,
    ) -> Path:
        """Save a model version snapshot.

        Returns:
            Path to the version directory.
        """
        version_dir = self._version_dir(model_id, version.version_id)
        version_dir.mkdir(parents=True, exist_ok=True)

        # Write SBML
        sbml_path = version_dir / version.sbml_filename
        cobra.io.write_sbml_model(cobra_model, str(sbml_path))
        logger.info("Saved SBML to %s", sbml_path)

        # Write metadata
        meta_path = version_dir / "meta.json"
        self._atomic_write_text(
            meta_path, json.dumps(self._version_to_dict(version), indent=2)
        )

        # Update history index
        history = self.load_history(model_id)
        # Replace if version_id already exists, else append
        history = [v for v in history if v.version_id != version.version_id]
        history.append(version)
        self.save_history(model_id, history)

        logger.info(
            "Saved version %s for model %s", version.version_id, model_id,
        )
        return version_dir

    def load_version(
        self, model_id: str, version_id: str
    ) -> tuple[cobra.Model, ModelVersion]:
        """Load a specific version.

        Returns:
            (cobra_model, version_metadata)

        Raises:
            FileNotFoundError: If the version directory or files are missing.
        """
        version_dir = self._version_dir(model_id, version_id)
        meta_path = version_dir / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"Version metadata not found: {meta_path}"
            )

        version = self._dict_to_version(
            json.loads(meta_path.read_text(encoding="utf-8"))
        )

        sbml_path = version_dir / version.sbml_filename
        if not sbml_path.exists():
            raise FileNotFoundError(f"SBML file not found: {sbml_path}")

        model = cobra.io.read_sbml_model(str(sbml_path))
        return model, version

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        """Write ``text`` atomically so a crash mid-write can't corrupt ``path``.

        Writes a sibling temp file then ``os.replace``s it into place (an atomic
        rename on the same filesystem). Without this, a truncated write to the
        shared history index would make an entire model's version history
        unreadable.
        """
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def load_history(self, model_id: str) -> list[ModelVersion]:
        """Load the full version history for a model."""
        history_path = self._model_dir(model_id) / "history.json"
        if not history_path.exists():
            return []

        try:
            data = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Version history for %s is unreadable (%s); treating as empty",
                model_id,
                exc,
            )
            return []
        return [self._dict_to_version(d) for d in data]

    def save_history(
        self, model_id: str, versions: list[ModelVersion]
    ) -> None:
        """Persist the history index."""
        model_dir = self._model_dir(model_id)
        model_dir.mkdir(parents=True, exist_ok=True)

        history_path = model_dir / "history.json"
        data = [self._version_to_dict(v) for v in versions]
        self._atomic_write_text(history_path, json.dumps(data, indent=2))

    def cleanup_old_versions(
        self, model_id: str, max_keep: int = 20
    ) -> int:
        """Remove oldest versions exceeding *max_keep*.

        Returns:
            Number of versions deleted.
        """
        history = self.load_history(model_id)
        if len(history) <= max_keep:
            return 0

        to_remove = history[: len(history) - max_keep]
        kept = history[len(history) - max_keep :]

        deleted = 0
        for version in to_remove:
            version_dir = self._version_dir(model_id, version.version_id)
            if version_dir.exists():
                shutil.rmtree(version_dir)
                deleted += 1
                logger.info(
                    "Cleaned up version %s for model %s",
                    version.version_id,
                    model_id,
                )

        self.save_history(model_id, kept)
        return deleted

    def update_description(
        self, model_id: str, version_id: str, new_description: str
    ) -> None:
        """Update the description of an existing version."""
        history = self.load_history(model_id)
        for v in history:
            if v.version_id == version_id:
                v.description = new_description
                break
        else:
            raise ValueError(f"Version {version_id} not found")
        self.save_history(model_id, history)

        # Also update meta.json
        meta_path = self._version_dir(model_id, version_id) / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["description"] = new_description
            meta_path.write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
        logger.info("Updated description for %s: %s", version_id, new_description)

    def rename_version(
        self, model_id: str, old_id: str, new_id: str
    ) -> None:
        """Rename a version ID: updates history, parent references, directory, and meta."""
        history = self.load_history(model_id)

        # Check new_id doesn't already exist
        if any(v.version_id == new_id for v in history):
            raise ValueError(f"Version ID '{new_id}' already exists")

        found = False
        for v in history:
            if v.version_id == old_id:
                v.version_id = new_id
                found = True
            # Update parent references
            if v.parent_version_id == old_id:
                v.parent_version_id = new_id
        if not found:
            raise ValueError(f"Version {old_id} not found")

        self.save_history(model_id, history)

        # Rename directory
        old_dir = self._version_dir(model_id, old_id)
        new_dir = self._version_dir(model_id, new_id)
        if old_dir.exists():
            old_dir.rename(new_dir)

        # Update meta.json inside renamed dir
        meta_path = new_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["version_id"] = new_id
            meta_path.write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )

        logger.info("Renamed version %s → %s", old_id, new_id)

    def delete_version(self, model_id: str, version_id: str) -> None:
        """Delete a version and its files."""
        history = self.load_history(model_id)
        new_history = [v for v in history if v.version_id != version_id]
        if len(new_history) == len(history):
            raise ValueError(f"Version {version_id} not found")

        # Remove files
        version_dir = self._version_dir(model_id, version_id)
        if version_dir.exists():
            shutil.rmtree(version_dir)

        self.save_history(model_id, new_history)
        logger.info("Deleted version %s for model %s", version_id, model_id)

    def get_next_version_id(self, model_id: str) -> str:
        """Generate the next sequential version ID (v001, v002, ...)."""
        history = self.load_history(model_id)
        if not history:
            return "v001"

        # Find the highest numeric suffix
        max_num = 0
        for v in history:
            vid = v.version_id
            if vid.startswith("v") and vid[1:].isdigit():
                max_num = max(max_num, int(vid[1:]))

        return f"v{max_num + 1:03d}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _model_dir(self, model_id: str) -> Path:
        return self._base_dir / model_id

    def _version_dir(self, model_id: str, version_id: str) -> Path:
        return self._model_dir(model_id) / version_id

    @staticmethod
    def _version_to_dict(version: ModelVersion) -> dict:
        """Serialize ModelVersion to a JSON-safe dict."""
        d: dict = {
            "version_id": version.version_id,
            "timestamp": version.timestamp,
            "parent_version_id": version.parent_version_id,
            "model_id": version.model_id,
            "description": version.description,
            "change_type": version.change_type,
            "task_pass_rate": version.task_pass_rate,
            "sbml_filename": version.sbml_filename,
            "restore_source_version_id": version.restore_source_version_id,
        }
        if version.diff is not None:
            d["diff"] = asdict(version.diff)
        else:
            d["diff"] = None
        return d

    @staticmethod
    def _dict_to_version(d: dict) -> ModelVersion:
        """Deserialize a dict into a ModelVersion."""
        diff_data = d.get("diff")
        diff: ModelDiff | None = None
        if diff_data is not None:
            diff = ModelDiff(
                reactions_added=diff_data.get("reactions_added", []),
                reactions_removed=diff_data.get("reactions_removed", []),
                reactions_modified=[
                    ReactionChange(**rc)
                    for rc in diff_data.get("reactions_modified", [])
                ],
                genes_added=diff_data.get("genes_added", []),
                genes_removed=diff_data.get("genes_removed", []),
                metabolites_added=diff_data.get("metabolites_added", []),
                metabolites_removed=diff_data.get("metabolites_removed", []),
            )

        description = d.get("description", "")
        change_type = d.get("change_type", "initial_load")
        restore_source_version_id = d.get("restore_source_version_id")
        if not restore_source_version_id:
            match = _RESTORE_DESC_RE.search(description)
            if match:
                restore_source_version_id = match.group(1)
                if "change_type" not in d:
                    change_type = "restore"

        return ModelVersion(
            version_id=d["version_id"],
            timestamp=d["timestamp"],
            parent_version_id=d.get("parent_version_id"),
            model_id=d.get("model_id", ""),
            description=description,
            change_type=change_type,
            diff=diff,
            task_pass_rate=d.get("task_pass_rate"),
            sbml_filename=d.get("sbml_filename", "model.xml"),
            restore_source_version_id=restore_source_version_id,
        )
