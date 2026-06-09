"""Tests for evidence engine."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.models import (
    EvaluationStatus,
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    EvidenceTier,
    ExternalIDs,
    Reaction,
)
from src.evidence.engine import EvidenceEngine
from src.utils.config import Config


class TestEvidenceEngine:
    @pytest.fixture
    def config(self):
        return Config(
            kegg_organism_code="eco",
            organism_name="Escherichia coli",
            batch_size=5,
        )

    @pytest.fixture
    def mock_engine(self, config):
        engine = EvidenceEngine(config)

        # Mock cache
        engine._cache = MagicMock()
        engine._cache.initialize = AsyncMock()
        engine._cache.close = AsyncMock()

        # Mock KEGG
        engine._kegg = MagicMock()
        engine._kegg.close = AsyncMock()
        engine._kegg.check_evidence = AsyncMock(
            return_value=[
                EvidenceItem(
                    source=EvidenceSource.KEGG,
                    strength=EvidenceStrength.STRONG,
                    description="KEGG reaction R00658 — substrate match: 100%, product match: 100%",
                    raw_data={
                        "kegg_id": "R00658",
                        "substrate_match": 1.0,
                        "product_match": 1.0,
                    },
                ),
            ]
        )

        # Mock mapper
        engine._mapper = MagicMock()
        engine._mapper.resolve = AsyncMock(
            return_value=ExternalIDs(
                reaction_id="ENO",
                bigg_id="ENO",
                ec_numbers=["4.2.1.11"],
                kegg_reaction_ids=["R00658"],
                kegg_substrate_ids=["C00631"],
                kegg_product_ids=["C00074", "C00001"],
            )
        )

        return engine

    @pytest.mark.asyncio
    async def test_evaluate_reaction(self, mock_engine, sample_reaction):
        ev = await mock_engine.evaluate_reaction(sample_reaction)
        assert ev.status == EvaluationStatus.EVALUATED
        assert ev.confidence_score > 0
        assert ev.evidence_tier == EvidenceTier.HIGH
        assert len(ev.items) >= 1
        assert ev.ec_numbers == ["4.2.1.11"]

    @pytest.mark.asyncio
    async def test_bigg_lookup_falls_back_from_kegg_mapping(
        self, mock_engine, sample_reaction
    ):
        """If direct BiGG lookup misses, KEGG->BiGG mappings are checked."""

        async def check_evidence(reaction, bigg_id=None):
            if bigg_id == "ENO_mapped":
                return [
                    EvidenceItem(
                        source=EvidenceSource.BIGG,
                        strength=EvidenceStrength.STRONG,
                        description="Mapped BiGG evidence",
                    )
                ]
            return [
                EvidenceItem(
                    source=EvidenceSource.BIGG,
                    strength=EvidenceStrength.ABSENT,
                    description="Direct BiGG lookup miss",
                )
            ]

        mock_engine._bigg = MagicMock()
        mock_engine._bigg.check_evidence = AsyncMock(side_effect=check_evidence)
        mock_engine._mapping_data = SimpleNamespace(
            rxn_kegg_to_bigg={"R00658": ["ENO_mapped"]}
        )

        ev = await mock_engine.evaluate_reaction(sample_reaction)

        bigg_items = [item for item in ev.items if item.source == EvidenceSource.BIGG]
        assert len(bigg_items) == 1
        assert bigg_items[0].strength == EvidenceStrength.STRONG
        assert bigg_items[0].raw_data["match_method"] == "kegg_to_bigg"
        assert bigg_items[0].raw_data["mapped_bigg_id"] == "ENO_mapped"

    @pytest.mark.asyncio
    async def test_evaluate_extracts_match_ratios(self, mock_engine, sample_reaction):
        ev = await mock_engine.evaluate_reaction(sample_reaction)
        assert ev.substrate_match_ratio == 1.0
        assert ev.product_match_ratio == 1.0

    @pytest.mark.asyncio
    async def test_evaluate_batch(self, mock_engine):
        reactions = [
            Reaction(id=f"RXN{i}", name=f"Reaction {i}", equation=f"a{i} -> b{i}")
            for i in range(10)
        ]
        results = await mock_engine.evaluate_batch(reactions)
        assert len(results) == 10
        assert all(ev.status == EvaluationStatus.EVALUATED for ev in results.values())

    @pytest.mark.asyncio
    async def test_get_result(self, mock_engine, sample_reaction):
        await mock_engine.evaluate_reaction(sample_reaction)
        result = mock_engine.get_result("ENO")
        assert result is not None
        assert result.confidence_score > 0

    @pytest.mark.asyncio
    async def test_clear_results(self, mock_engine, sample_reaction):
        await mock_engine.evaluate_reaction(sample_reaction)
        mock_engine.clear_results()
        assert mock_engine.get_result("ENO") is None

    @pytest.mark.asyncio
    async def test_close(self, mock_engine):
        kegg = mock_engine._kegg
        await mock_engine.close()
        assert kegg is not None
        kegg.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_evaluate_handles_kegg_exception(self, mock_engine, sample_reaction):
        """KEGG failure should result in ERROR status."""
        mock_engine._kegg.check_evidence = AsyncMock(side_effect=RuntimeError("KEGG down"))
        ev = await mock_engine.evaluate_reaction(sample_reaction)
        assert ev.status == EvaluationStatus.ERROR
        assert ev.error_message is not None

    @pytest.mark.asyncio
    async def test_evaluate_handles_mapper_exception(self, mock_engine, sample_reaction):
        """Mapper failure should result in ERROR status."""
        mock_engine._mapper.resolve = AsyncMock(side_effect=RuntimeError("Mapper crashed"))
        ev = await mock_engine.evaluate_reaction(sample_reaction)
        assert ev.status == EvaluationStatus.ERROR
        assert ev.error_message is not None

    @pytest.mark.asyncio
    async def test_batch_cancel(self, mock_engine):
        """Cancelling a batch should stop evaluation."""
        import asyncio

        reactions = [Reaction(id=f"RXN{i}", name=f"R{i}", equation="a -> b") for i in range(20)]
        cancel = asyncio.Event()
        cancel.set()  # Cancel immediately
        results = await mock_engine.evaluate_batch(reactions, cancel_event=cancel)
        # Should have stopped early
        assert len(results) < 20

    @pytest.mark.asyncio
    async def test_batch_progress_callback(self, mock_engine):
        """Progress callback should be called during batch."""
        progress_calls = []

        def on_progress(current, total, rxn_id):
            progress_calls.append((current, total, rxn_id))

        reactions = [Reaction(id=f"RXN{i}", name=f"R{i}", equation="a -> b") for i in range(5)]
        await mock_engine.evaluate_batch(reactions, progress_callback=on_progress)
        assert len(progress_calls) >= 1

    @pytest.mark.asyncio
    async def test_batch_size_zero_no_infinite_loop(self, config):
        """batch_size=0 should not cause infinite loop (bug fix)."""
        config.batch_size = 0
        engine = EvidenceEngine(config)
        engine._cache = MagicMock()
        engine._mapper = MagicMock()
        engine._mapper.resolve = AsyncMock(return_value=ExternalIDs(reaction_id="X"))
        engine._kegg = MagicMock()
        engine._kegg.check_evidence = AsyncMock(return_value=[])

        reactions = [Reaction(id="R1", name="R1", equation="a -> b")]
        results = await engine.evaluate_batch(reactions)
        assert len(results) == 1
