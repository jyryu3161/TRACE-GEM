"""Tests for VersionStorage and VersionManager."""

from __future__ import annotations

from pathlib import Path

import cobra
import pytest

from src.core.models import (
    MetabolicTask,
    ModelDiff,
    ModelVersion,
    ReactionChange,
    TaskResult,
)
from src.utils.config import Config
from src.versioning.storage import VersionStorage
from src.versioning.version_manager import VersionManager


@pytest.fixture
def tmp_storage(tmp_path: Path) -> VersionStorage:
    return VersionStorage(base_dir=tmp_path)


def _make_cobra_model(model_id: str = "test") -> cobra.Model:
    """Build a minimal cobra.Model for serialization tests."""
    model = cobra.Model(model_id)
    m1 = cobra.Metabolite("m1_c", compartment="c")
    rxn = cobra.Reaction("R1")
    rxn.add_metabolites({m1: -1.0})
    rxn.lower_bound = 0.0
    rxn.upper_bound = 1000.0
    model.add_reactions([rxn])
    return model


def _make_version(
    version_id: str = "v001",
    model_id: str = "test_model",
    change_type: str = "initial_load",
    description: str = "initial",
    diff: ModelDiff | None = None,
) -> ModelVersion:
    return ModelVersion(
        version_id=version_id,
        timestamp="2026-02-21T00:00:00",
        model_id=model_id,
        change_type=change_type,
        description=description,
        diff=diff,
    )


class TestVersionStorageSaveLoad:
    """Tests for save_version and load_version."""

    def test_save_and_load_version(self, tmp_storage: VersionStorage) -> None:
        model = _make_cobra_model()
        version = _make_version()

        path = tmp_storage.save_version("test_model", version, model)

        assert path.exists()
        assert (path / "model.xml").exists()
        assert (path / "meta.json").exists()

        loaded_model, loaded_version = tmp_storage.load_version(
            "test_model", "v001"
        )
        assert loaded_version.version_id == "v001"
        assert loaded_version.change_type == "initial_load"
        assert len(loaded_model.reactions) == 1

    def test_save_version_with_diff(self, tmp_storage: VersionStorage) -> None:
        model = _make_cobra_model()
        diff = ModelDiff(
            reactions_added=["R2"],
            reactions_modified=[
                ReactionChange("R1", "lower_bound", "0.0", "-1000.0"),
            ],
            genes_added=["g1"],
        )
        version = _make_version(version_id="v002", diff=diff)

        tmp_storage.save_version("test_model", version, model)
        _, loaded = tmp_storage.load_version("test_model", "v002")

        assert loaded.diff is not None
        assert loaded.diff.reactions_added == ["R2"]
        assert len(loaded.diff.reactions_modified) == 1
        assert loaded.diff.genes_added == ["g1"]

    def test_legacy_restore_description_infers_source(self) -> None:
        version = VersionStorage._dict_to_version(
            {
                "version_id": "v006",
                "timestamp": "2026-06-08T00:05:00+00:00",
                "parent_version_id": "v005",
                "description": "Restored to version v003",
            }
        )

        assert version.change_type == "restore"
        assert version.restore_source_version_id == "v003"

    def test_load_missing_version_raises(
        self, tmp_storage: VersionStorage
    ) -> None:
        with pytest.raises(FileNotFoundError):
            tmp_storage.load_version("no_model", "v999")


class TestVersionStorageHistory:
    """Tests for history load/save."""

    def test_empty_history(self, tmp_storage: VersionStorage) -> None:
        history = tmp_storage.load_history("no_model")
        assert history == []

    def test_save_and_load_history(self, tmp_storage: VersionStorage) -> None:
        model = _make_cobra_model()
        v1 = _make_version(version_id="v001")
        v2 = _make_version(version_id="v002", change_type="gap_fill")

        tmp_storage.save_version("test_model", v1, model)
        tmp_storage.save_version("test_model", v2, model)

        history = tmp_storage.load_history("test_model")
        assert len(history) == 2
        assert history[0].version_id == "v001"
        assert history[1].version_id == "v002"

    def test_corrupt_history_degrades_gracefully(
        self, tmp_storage: VersionStorage
    ) -> None:
        """A truncated/corrupt history index returns [] instead of crashing."""
        model = _make_cobra_model()
        tmp_storage.save_version("test_model", _make_version("v001"), model)

        history_path = tmp_storage._model_dir("test_model") / "history.json"
        history_path.write_text('[{"version_id": "v001", trunca', encoding="utf-8")

        # Must not raise JSONDecodeError up into save_version/get_next_version_id.
        assert tmp_storage.load_history("test_model") == []

    def test_save_history_is_atomic(self, tmp_storage: VersionStorage) -> None:
        """History is written atomically and leaves no leftover temp file."""
        model = _make_cobra_model()
        tmp_storage.save_version("test_model", _make_version("v001"), model)

        model_dir = tmp_storage._model_dir("test_model")
        assert (model_dir / "history.json").exists()
        assert not (model_dir / "history.json.tmp").exists()


class TestVersionStorageCleanup:
    """Tests for cleanup_old_versions."""

    def test_cleanup_removes_oldest(self, tmp_storage: VersionStorage) -> None:
        model = _make_cobra_model()
        for i in range(1, 6):
            v = _make_version(version_id=f"v{i:03d}")
            tmp_storage.save_version("test_model", v, model)

        deleted = tmp_storage.cleanup_old_versions("test_model", max_keep=3)

        assert deleted == 2
        history = tmp_storage.load_history("test_model")
        assert len(history) == 3
        assert history[0].version_id == "v003"

    def test_cleanup_noop_under_limit(
        self, tmp_storage: VersionStorage
    ) -> None:
        model = _make_cobra_model()
        v = _make_version()
        tmp_storage.save_version("test_model", v, model)

        deleted = tmp_storage.cleanup_old_versions("test_model", max_keep=20)
        assert deleted == 0


class TestVersionStorageNextId:
    """Tests for get_next_version_id."""

    def test_first_version(self, tmp_storage: VersionStorage) -> None:
        assert tmp_storage.get_next_version_id("new_model") == "v001"

    def test_increments(self, tmp_storage: VersionStorage) -> None:
        model = _make_cobra_model()
        for i in range(1, 4):
            v = _make_version(version_id=f"v{i:03d}")
            tmp_storage.save_version("test_model", v, model)

        assert tmp_storage.get_next_version_id("test_model") == "v004"


# ======================================================================
# VersionManager tests
# ======================================================================


def _make_model_with_rxns(rxn_ids: list[str] | None = None) -> cobra.Model:
    """Create a cobra.Model with named reactions for VersionManager tests."""
    model = cobra.Model("test_model")
    for rid in rxn_ids or []:
        rxn = cobra.Reaction(rid)
        rxn.name = rid
        rxn.lower_bound = -1000.0
        rxn.upper_bound = 1000.0
        met = cobra.Metabolite(f"{rid}_met_c", compartment="c")
        rxn.add_metabolites({met: -1.0})
        model.add_reactions([rxn])
    return model


@pytest.fixture
def vm_config(tmp_path: Path) -> Config:
    return Config(
        version_dir=str(tmp_path / "versions"),
        max_versions=5,
    )


@pytest.fixture
def vm(vm_config: Config) -> VersionManager:
    return VersionManager(vm_config)


class TestVersionManagerSetBase:
    def test_creates_v001(self, vm: VersionManager) -> None:
        model = _make_model_with_rxns(["PFK", "ENO"])
        vm.set_base_model(model, "test_model")

        assert vm.current_version is not None
        assert vm.current_version.version_id == "v001"
        assert vm.current_version.change_type == "initial_load"
        assert vm.current_version.model_id == "test_model"

    def test_initial_description(self, vm: VersionManager) -> None:
        model = _make_model_with_rxns(["PFK", "ENO", "GAPD"])
        vm.set_base_model(model, "test_model")

        desc = vm.current_version.description
        assert "Initial model load" in desc
        assert "3 reactions" in desc

    def test_history_has_one_entry(self, vm: VersionManager) -> None:
        model = _make_model_with_rxns(["PFK"])
        vm.set_base_model(model, "test_model")

        history = vm.get_history()
        assert len(history) == 1
        assert history[0].version_id == "v001"

    async def test_reopening_resumes_existing_history(
        self, vm_config: Config
    ) -> None:
        """Reopening a model with existing history resumes its tip, not a new root.

        Regression: previously every load appended a fresh parentless
        ``initial_load`` version, orphaning the prior edit chain and splitting
        the history graph into multiple disconnected roots.
        """
        vm1 = VersionManager(vm_config)
        vm1.set_base_model(_make_model_with_rxns(["PFK"]), "test_model")  # v001
        await vm1.save_version(
            _make_model_with_rxns(["PFK", "ENO"]), "gap_fill"
        )  # v002

        # Simulate reopening the model: a fresh manager over the same storage.
        vm2 = VersionManager(vm_config)
        vm2.set_base_model(_make_model_with_rxns(["PFK", "ENO"]), "test_model")

        history = vm2.get_history()
        assert len(history) == 2  # no extra initial_load root was appended
        assert vm2.current_version is not None
        assert vm2.current_version.version_id == "v002"  # resumed at the tip
        roots = [v for v in history if v.parent_version_id is None]
        assert len(roots) == 1  # exactly one parentless root remains


class TestVersionManagerSave:
    async def test_saves_gap_fill(self, vm: VersionManager) -> None:
        vm.set_base_model(_make_model_with_rxns(["PFK", "ENO"]), "test_model")

        modified = _make_model_with_rxns(["PFK", "ENO", "GLNS"])
        version = await vm.save_version(modified, "gap_fill")

        assert version.version_id == "v002"
        assert version.change_type == "gap_fill"
        assert version.parent_version_id == "v001"
        assert "Gap-filling" in version.description
        assert version.diff is not None
        assert "GLNS" in version.diff.reactions_added

    async def test_saves_with_task_results(self, vm: VersionManager) -> None:
        vm.set_base_model(_make_model_with_rxns(["PFK"]), "test_model")

        task = MetabolicTask(
            task_id="T1", task_type="Reaction", target_id="PFK"
        )
        results = [
            TaskResult(task=task, passed=True, actual_value=1.0),
            TaskResult(task=task, passed=False, actual_value=0.0),
            TaskResult(task=task, passed=True, actual_value=0.5),
        ]

        version = await vm.save_version(
            _make_model_with_rxns(["PFK"]),
            "manual_edit",
            task_results=results,
        )
        assert version.task_pass_rate == "2/3"

    async def test_saves_with_custom_description(
        self, vm: VersionManager
    ) -> None:
        vm.set_base_model(_make_model_with_rxns(["PFK"]), "test_model")

        version = await vm.save_version(
            _make_model_with_rxns(["PFK"]),
            "manual_edit",
            custom_description="Custom description here",
        )
        assert version.description == "Custom description here"

    async def test_updates_current_version(self, vm: VersionManager) -> None:
        vm.set_base_model(_make_model_with_rxns(["PFK"]), "test_model")

        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO"]), "gap_fill"
        )
        assert vm.current_version.version_id == "v002"

        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO", "GAPD"]), "gap_fill"
        )
        assert vm.current_version.version_id == "v003"

    async def test_raises_without_base(self, vm_config: Config) -> None:
        mgr = VersionManager(vm_config)
        with pytest.raises(RuntimeError, match="No base model"):
            await mgr.save_version(
                _make_model_with_rxns(["PFK"]), "gap_fill"
            )

    async def test_cleanup_old_versions(self, vm_config: Config) -> None:
        vm_config.max_versions = 3
        mgr = VersionManager(vm_config)

        mgr.set_base_model(_make_model_with_rxns(["PFK"]), "test_model")

        for i in range(4):
            rxn_ids = ["PFK"] + [f"RXN{j}" for j in range(i + 1)]
            await mgr.save_version(_make_model_with_rxns(rxn_ids), "gap_fill")

        history = mgr.get_history()
        assert len(history) == 3


class TestVersionManagerRestore:
    async def test_restore_creates_new_version(
        self, vm: VersionManager
    ) -> None:
        vm.set_base_model(
            _make_model_with_rxns(["PFK", "ENO"]), "test_model"
        )
        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO", "GLNS"]), "gap_fill"
        )

        restored_model = vm.restore_version("v001")
        assert vm.current_version.version_id == "v003"
        assert vm.current_version.change_type == "restore"
        assert "Restored to version v001" in vm.current_version.description
        assert vm.current_version.restore_source_version_id == "v001"

        rxn_ids = {r.id for r in restored_model.reactions}
        assert "PFK" in rxn_ids
        assert "ENO" in rxn_ids
        assert "GLNS" not in rxn_ids

    async def test_restore_diff_captured(self, vm: VersionManager) -> None:
        vm.set_base_model(
            _make_model_with_rxns(["PFK", "ENO"]), "test_model"
        )
        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO", "GLNS"]), "gap_fill"
        )

        vm.restore_version("v001")
        diff = vm.current_version.diff
        assert diff is not None
        assert "GLNS" in diff.reactions_removed


class TestVersionManagerHistory:
    async def test_returns_all_versions(self, vm: VersionManager) -> None:
        vm.set_base_model(_make_model_with_rxns(["PFK"]), "test_model")
        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO"]), "gap_fill"
        )
        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO", "GAPD"]), "gap_fill"
        )

        history = vm.get_history()
        assert len(history) == 3
        assert [v.version_id for v in history] == ["v001", "v002", "v003"]


class TestVersionManagerCompare:
    async def test_compare_two_versions(self, vm: VersionManager) -> None:
        vm.set_base_model(
            _make_model_with_rxns(["PFK", "ENO"]), "test_model"
        )
        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO", "GLNS"]), "gap_fill"
        )

        diff = vm.compare_versions("v001", "v002")
        assert "GLNS" in diff.reactions_added
        assert diff.reactions_removed == []

    async def test_compare_reverse_order(self, vm: VersionManager) -> None:
        vm.set_base_model(
            _make_model_with_rxns(["PFK", "ENO"]), "test_model"
        )
        await vm.save_version(
            _make_model_with_rxns(["PFK", "ENO", "GLNS"]), "gap_fill"
        )

        diff = vm.compare_versions("v002", "v001")
        assert "GLNS" in diff.reactions_removed
        assert diff.reactions_added == []
