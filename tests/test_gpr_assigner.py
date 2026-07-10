"""Tests for GPRAssigner."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.core.models import CandidateReaction, Reaction
from src.gapfill.gpr_assigner import GPRAssigner


class TestGPRAssigner:
    @pytest.fixture
    def assigner(self) -> GPRAssigner:
        return GPRAssigner(organism_code="eco", cache_manager=None)

    async def test_assign_gpr_single_ko(self, assigner: GPRAssigner) -> None:
        """Single KO with multiple genes -> 'gene1 or gene2'."""
        # Mock KEGG responses
        ko_response = "rn:R00001\tko:K00844\n"
        gene_response = "ko:K00844\teco:b2388\nko:K00844\teco:b1101\n"

        with patch.object(assigner, "_kegg_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [ko_response, gene_response]
            gpr, genes = await assigner.assign_gpr("R00001")

        assert gpr == "b2388 or b1101"
        assert set(genes) == {"b2388", "b1101"}

    async def test_assign_gpr_single_ko_single_gene(self, assigner: GPRAssigner) -> None:
        """Single KO with one gene -> 'gene1' (no 'or')."""
        ko_response = "rn:R00001\tko:K00844\n"
        gene_response = "ko:K00844\teco:b2388\n"

        with patch.object(assigner, "_kegg_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [ko_response, gene_response]
            gpr, genes = await assigner.assign_gpr("R00001")

        assert gpr == "b2388"
        assert genes == ["b2388"]

    async def test_assign_gpr_multiple_kos(self, assigner: GPRAssigner) -> None:
        """Multiple KO links do not imply a subunit complex."""
        ko_response = "rn:R00002\tko:K00134\nrn:R00002\tko:K00150\n"
        gene_response_1 = "ko:K00134\teco:b1779\n"
        gene_response_2 = "ko:K00150\teco:b1780\n"

        with patch.object(assigner, "_kegg_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [ko_response, gene_response_1, gene_response_2]
            gpr, genes = await assigner.assign_gpr("R00002")

        assert gpr == ""
        assert set(genes) == {"b1779", "b1780"}

    async def test_assign_gpr_multiple_kos_multiple_genes(self, assigner: GPRAssigner) -> None:
        """Ambiguous multiple KO groups retain genes but not an invented GPR."""
        ko_response = "rn:R00003\tko:K00001\nrn:R00003\tko:K00002\n"
        gene_response_1 = "ko:K00001\teco:b0001\nko:K00001\teco:b0002\n"
        gene_response_2 = "ko:K00002\teco:b0003\n"

        with patch.object(assigner, "_kegg_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [ko_response, gene_response_1, gene_response_2]
            gpr, genes = await assigner.assign_gpr("R00003")

        assert gpr == ""
        assert set(genes) == {"b0001", "b0002", "b0003"}

    async def test_assign_gpr_no_ko_found(self, assigner: GPRAssigner) -> None:
        """No KO found -> empty GPR."""
        with patch.object(assigner, "_kegg_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            gpr, genes = await assigner.assign_gpr("R99999")

        assert gpr == ""
        assert genes == []

    async def test_assign_gpr_ko_but_no_genes(self, assigner: GPRAssigner) -> None:
        """KO found but no genes in organism -> empty GPR."""
        ko_response = "rn:R00001\tko:K00844\n"

        with patch.object(assigner, "_kegg_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [ko_response, None]
            gpr, genes = await assigner.assign_gpr("R00001")

        assert gpr == ""
        assert genes == []

    async def test_assign_batch(self, assigner: GPRAssigner) -> None:
        """assign_batch modifies candidates in place."""
        rxn_a = Reaction(
            id="RXN_A",
            name="A",
            equation="A -> B",
            annotation={"kegg.reaction": ["R00001"]},
        )
        rxn_b = Reaction(
            id="RXN_B",
            name="B",
            equation="C -> D",
            annotation={},
        )
        candidates = [
            CandidateReaction(reaction=rxn_a),
            CandidateReaction(reaction=rxn_b),
        ]

        # Mock assign_gpr to return deterministic results
        with patch.object(assigner, "assign_gpr", new_callable=AsyncMock) as mock_assign:
            mock_assign.return_value = ("b2388 or b1101", ["b2388", "b1101"])
            progress_calls: list[tuple[int, int, str]] = []
            await assigner.assign_batch(
                candidates,
                progress_callback=lambda c, t, d: progress_calls.append((c, t, d)),
            )

        # RXN_A has kegg.reaction annotation -> GPR assigned
        assert candidates[0].assigned_gpr == "b2388 or b1101"
        assert candidates[0].kegg_organism_genes == ["b2388", "b1101"]

        # RXN_B has no kegg annotation -> GPR stays empty
        assert candidates[1].assigned_gpr == ""
        assert candidates[1].kegg_organism_genes == []

        # Progress callback called for each candidate
        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2, "RXN_A")
        assert progress_calls[1] == (2, 2, "RXN_B")

    async def test_assign_batch_normalizes_kegg_reaction_uri(self, assigner: GPRAssigner) -> None:
        """identifiers.org KEGG reaction annotations are normalized."""
        rxn = Reaction(
            id="RXN_URI",
            name="URI",
            equation="A -> B",
            annotation={"kegg.reaction": ["http://identifiers.org/kegg.reaction/R01324"]},
        )
        candidate = CandidateReaction(reaction=rxn)

        with patch.object(assigner, "assign_gpr", new_callable=AsyncMock) as mock_assign:
            mock_assign.return_value = ("b0118", ["b0118"])
            await assigner.assign_batch([candidate])

        mock_assign.assert_awaited_once_with("R01324", allowed_gene_ids=None)
        assert candidate.assigned_gpr == "b0118"

    async def test_assign_gpr_filters_to_genes_present_in_model(
        self, assigner: GPRAssigner
    ) -> None:
        ko_response = "rn:R00001\tko:K00844\n"
        gene_response = "ko:K00844\teco:b2388\nko:K00844\teco:foreign\n"
        with patch.object(assigner, "_kegg_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [ko_response, gene_response]
            gpr, genes = await assigner.assign_gpr(
                "R00001",
                allowed_gene_ids={"b2388"},
            )

        assert gpr == "b2388"
        assert genes == ["b2388"]

    async def test_close(self, assigner: GPRAssigner) -> None:
        """close() handles None session gracefully."""
        await assigner.close()  # Should not raise

    async def test_parse_link_response(self, assigner: GPRAssigner) -> None:
        """_parse_link_response strips prefixes correctly."""
        text = "rn:R00001\tko:K00844\nrn:R00001\tko:K00845\n"
        result = assigner._parse_link_response(text)
        assert result == ["K00844", "K00845"]

    async def test_parse_link_response_empty(self, assigner: GPRAssigner) -> None:
        """_parse_link_response handles empty input."""
        assert assigner._parse_link_response("") == []
        assert assigner._parse_link_response("\n") == []
