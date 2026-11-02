"""UniProtKB search: protein or gene name -> accession.

UNVERIFIED against the live API: the docs were unreachable when this was written, so the response
keys below (results[].primaryAccession, proteinDescription.recommendedName.fullName.value,
genes[].geneName.value) come from memory. Anything missing is an `error`, never a crash.
`scripts/live_smoke.py` checks them against the live API.
"""

from __future__ import annotations

import logging
from typing import Literal

from cloudyreader.models import Resolution
from cloudyreader.resolvers.http import (
    FailureStatus,
    HttpClient,
    HttpError,
    clean_query,
    dig,
    failure_status,
    shape,
)

log = logging.getLogger(__name__)

_URL = "https://rest.uniprot.org/uniprotkb/search"
_FIELDS = "accession,protein_name,gene_names"


class UniProtResolver:
    """Look a name up in UniProtKB. Names are metadata only: they are never spoken (R5).

    The search is free text, so any common word finds some protein. `ok` means UniProt answered,
    not that the token is a protein: callers must combine it with the NER label.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def resolve(
        self,
        name: str,
        *,
        kind: Literal["protein", "gene"] = "protein",
        deadline: float | None = None,
    ) -> Resolution:
        """Never raises for network trouble. `kind` is echoed: UniProt cannot tell a gene symbol
        from a protein name, the NER label can."""
        query = clean_query(name)
        if query is None:
            return _failed(name, kind, "not_found")
        params = {"query": query, "fields": _FIELDS, "format": "json", "size": "1"}
        try:
            data = self._http.get_json(_URL, params, deadline=deadline)
        except HttpError as exc:
            return _failed(name, kind, failure_status(exc))
        results = dig(data, "results")
        if isinstance(results, list) and not results:
            return _failed(name, kind, "not_found")
        accession = dig(results, 0, "primaryAccession")
        if not isinstance(accession, str) or not accession:
            log.warning("UniProt sent an unexpected body: %s", shape(data))
            return _failed(name, kind, "error")
        ids = {"accession": accession}
        gene = dig(results, 0, "genes", 0, "geneName", "value")
        if isinstance(gene, str) and gene:
            ids["gene"] = gene
        protein = dig(results, 0, "proteinDescription", "recommendedName", "fullName", "value")
        preferred = (gene, protein) if kind == "gene" else (protein, gene)
        canonical = next((n for n in preferred if isinstance(n, str) and n), None)
        return Resolution(name, kind, canonical, ids, "uniprot", "ok")


def _failed(name: str, kind: Literal["protein", "gene"], status: FailureStatus) -> Resolution:
    return Resolution(name, kind, None, {}, "uniprot", status)
