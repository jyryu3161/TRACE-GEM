"""UniProt REST API client."""

from __future__ import annotations

import logging

from src.api.base_client import BaseAPIClient
from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)
from src.utils.constants import RATE_LIMITS, UNIPROT_API_BASE

logger = logging.getLogger("gem_evaluator.api.uniprot")


class UniProtClient(BaseAPIClient):
    """Client for the UniProt REST API."""

    def __init__(self, taxonomy_id: str = "83333", cache_manager=None) -> None:
        super().__init__(
            name="uniprot",
            base_url=UNIPROT_API_BASE,
            rate=RATE_LIMITS["uniprot"],
            cache_manager=cache_manager,
        )
        self.taxonomy_id = taxonomy_id

    async def search_by_gene(self, gene_id: str) -> dict | str | None:
        """Search UniProt for entries matching a gene name in the organism."""
        query = f"(gene:{gene_id}) AND (organism_id:{self.taxonomy_id})"
        params = {
            "query": query,
            "format": "json",
            "size": "5",
            "fields": "accession,gene_names,protein_name,organism_name,"
            "reviewed,ec,go,protein_existence",
        }
        return await self.get(
            "/uniprotkb/search",
            params=params,
            cache_key=f"uniprot:gene:{gene_id}:{self.taxonomy_id}",
            cache_ttl=7 * 24 * 3600,
        )

    async def search_by_ec(self, ec_number: str) -> dict | str | None:
        """Search UniProt for entries with a specific EC number in the organism."""
        query = f"(ec:{ec_number}) AND (organism_id:{self.taxonomy_id})"
        params = {
            "query": query,
            "format": "json",
            "size": "5",
            "fields": "accession,gene_names,protein_name,organism_name,"
            "reviewed,ec,go,protein_existence",
        }
        return await self.get(
            "/uniprotkb/search",
            params=params,
            cache_key=f"uniprot:ec:{ec_number}:{self.taxonomy_id}",
            cache_ttl=7 * 24 * 3600,
        )

    async def check_evidence(
        self,
        reaction: Reaction,
        ec_numbers: list[str] | None = None,
        **kwargs,
    ) -> list[EvidenceItem]:
        """Check UniProt for protein/gene evidence supporting this reaction."""
        items: list[EvidenceItem] = []

        # Strategy 1: Search by gene IDs from GPR
        for gene_id in reaction.genes[:3]:
            data = await self.search_by_gene(gene_id)
            if data and isinstance(data, dict):
                results = data.get("results", [])
                if results:
                    entry = results[0]
                    reviewed = entry.get("entryType", "") == "UniProtKB reviewed (Swiss-Prot)"
                    accession = entry.get("primaryAccession", "")

                    # Check EC match
                    entry_ecs = self._extract_ec_numbers(entry)
                    ec_match = bool(ec_numbers and set(ec_numbers) & set(entry_ecs))

                    if reviewed and ec_match:
                        strength = EvidenceStrength.STRONG
                        desc = f"Reviewed UniProt entry {accession} with matching EC"
                    elif reviewed:
                        strength = EvidenceStrength.MODERATE
                        desc = f"Reviewed UniProt entry {accession} for gene {gene_id}"
                    else:
                        strength = EvidenceStrength.WEAK
                        desc = f"TrEMBL entry {accession} for gene {gene_id}"

                    items.append(
                        EvidenceItem(
                            source=EvidenceSource.UNIPROT,
                            strength=strength,
                            description=desc,
                            url=f"https://www.uniprot.org/uniprotkb/{accession}",
                            raw_data={
                                "accession": accession,
                                "reviewed": reviewed,
                                "ec_match": ec_match,
                                "gene": gene_id,
                            },
                        )
                    )
                    break  # Found a good match

        # Strategy 2: Search by EC number if no gene match
        if not items and ec_numbers:
            for ec in ec_numbers[:2]:
                data = await self.search_by_ec(ec)
                if data and isinstance(data, dict):
                    results = data.get("results", [])
                    if results:
                        entry = results[0]
                        reviewed = entry.get("entryType", "") == "UniProtKB reviewed (Swiss-Prot)"
                        accession = entry.get("primaryAccession", "")

                        strength = EvidenceStrength.MODERATE if reviewed else EvidenceStrength.WEAK
                        desc = (
                            f"UniProt entry {accession} with EC {ec} "
                            f"({'reviewed' if reviewed else 'unreviewed'})"
                        )

                        items.append(
                            EvidenceItem(
                                source=EvidenceSource.UNIPROT,
                                strength=strength,
                                description=desc,
                                url=f"https://www.uniprot.org/uniprotkb/{accession}",
                                raw_data={"accession": accession, "ec": ec, "reviewed": reviewed},
                            )
                        )
                        break

        if not items:
            items.append(
                EvidenceItem(
                    source=EvidenceSource.UNIPROT,
                    strength=EvidenceStrength.ABSENT,
                    description="No UniProt evidence found for this reaction",
                )
            )

        return items

    def _extract_ec_numbers(self, entry: dict) -> list[str]:
        """Extract EC numbers from a UniProt JSON entry."""
        ecs = []
        # proteinDescription -> recommendedName -> ecNumbers
        protein_desc = entry.get("proteinDescription", {})
        rec_name = protein_desc.get("recommendedName", {})
        for ec_entry in rec_name.get("ecNumbers", []):
            ecs.append(ec_entry.get("value", ""))
        # Also check submittedName
        for sub in protein_desc.get("submissionNames", []):
            for ec_entry in sub.get("ecNumbers", []):
                ecs.append(ec_entry.get("value", ""))
        return [e for e in ecs if e]
