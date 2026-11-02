"""PubChem PUG REST: chemical name -> CID, formula and IUPAC name."""

from __future__ import annotations

import logging

from cloudyreader.models import Resolution
from cloudyreader.resolvers.http import (
    FailureStatus,
    HttpClient,
    HttpError,
    clean_query,
    dig,
    failure_status,
    quote_segment,
    shape,
)

log = logging.getLogger(__name__)

_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/IUPACName,MolecularFormula/JSON"


class PubChemResolver:
    """Look a name up in PubChem. The IUPAC name is metadata only: it is never spoken (R5)."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def resolve(self, name: str, *, deadline: float | None = None) -> Resolution:
        """Never raises for network trouble: 404 is `not_found`, the rest become statuses."""
        query = clean_query(name)
        if query is None:
            return _resolution(name, "not_found")
        try:
            data = self._http.get_json(_URL.format(name=quote_segment(query)), deadline=deadline)
        except HttpError as exc:
            return _resolution(name, failure_status(exc))
        row = dig(data, "PropertyTable", "Properties", 0)
        cid = dig(row, "CID")
        if not isinstance(cid, int | str):
            # A 404 is the only "no such compound" answer, so anything else here is a format change.
            log.warning("PubChem sent an unexpected body: %s", shape(data))
            return _resolution(name, "error")
        ids = {"cid": str(cid)}
        formula = dig(row, "MolecularFormula")
        if isinstance(formula, str) and formula:
            ids["formula"] = formula
        iupac = dig(row, "IUPACName")
        canonical = iupac if isinstance(iupac, str) and iupac else None
        return Resolution(name, "chemical", canonical, ids, "pubchem", "ok")


def _resolution(name: str, status: FailureStatus) -> Resolution:
    return Resolution(name, "chemical", None, {}, "pubchem", status)
