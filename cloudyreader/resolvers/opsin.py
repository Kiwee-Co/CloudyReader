"""OPSIN batch resolver: IUPAC name -> SMILES, one JVM start per batch."""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from cloudyreader.models import Resolution

log = logging.getLogger(__name__)

_Status = Literal["ok", "not_found", "timeout", "error"]
_Outcome = tuple[_Status, str | None]  # status, SMILES
_NOT_FOUND: _Outcome = ("not_found", None)


def _jar() -> Path:
    # find_spec leaves py2opsin unimported: its import runs a bare `java -version`.
    spec = importlib.util.find_spec("py2opsin")
    folders = spec.submodule_search_locations if spec else None
    jars = sorted(Path(folders[0]).glob("opsin-cli-*.jar")) if folders else []
    if not jars:
        raise FileNotFoundError("py2opsin or its bundled OPSIN jar is missing")
    return jars[-1]


def _java() -> Path:
    import jdk4py  # lazy: a broken install must degrade to status "error", not fail at startup

    return jdk4py.JAVA


def _run_opsin(names: list[str], timeout_s: float) -> dict[str, str]:
    """Start OPSIN once for all `names`. Maps each name to its SMILES, or "" when unparseable."""
    java, jar = _java(), _jar()
    # A private directory keeps the names file out of the CWD and apart from concurrent batches.
    with tempfile.TemporaryDirectory(prefix="cloudyreader-opsin-") as tmp:
        names_file = Path(tmp) / "names.txt"
        names_file.write_text("\n".join(names) + "\n", encoding="utf-8")
        proc = subprocess.run(
            [str(java), "-jar", str(jar), "-osmi", str(names_file)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()[-200:]
        raise RuntimeError(f"OPSIN exited {proc.returncode}: {detail}")
    lines = proc.stdout.decode(errors="replace").splitlines()
    # OPSIN answers one line per name ("" when it cannot parse one); any other count is untrusted.
    if len(lines) != len(names):
        raise RuntimeError(f"OPSIN gave {len(lines)} answer(s) for {len(names)} name(s)")
    return {name: line.strip() for name, line in zip(names, lines, strict=True)}


def _lookup(batch: list[str], timeout_s: float) -> dict[str, _Outcome]:
    try:
        smiles = _run_opsin(batch, timeout_s)
    except subprocess.TimeoutExpired:
        log.warning("OPSIN timed out after %.1fs on %d name(s)", timeout_s, len(batch))
        return dict.fromkeys(batch, ("timeout", None))
    except Exception as exc:  # a crashed OPSIN must not take the reader down
        log.warning("OPSIN failed on %d name(s): %s", len(batch), exc)
        return dict.fromkeys(batch, ("error", None))
    return {name: ("ok", found) if found else _NOT_FOUND for name, found in smiles.items()}


class OpsinResolver:
    """Resolve IUPAC names to SMILES with the OPSIN jar that py2opsin bundles.

    The answer only decides HOW a token is spoken (R5): it carries a SMILES, never a common name.
    """

    def resolve_batch(
        self, names: Sequence[str], *, timeout_s: float = 20.0
    ) -> dict[str, Resolution]:
        """Resolve all `names` with one JVM start. Never raises: failures become statuses.

        Keys are the inputs as given. Names are whitespace-normalized and deduplicated before
        OPSIN sees them. `not_found`: OPSIN cannot parse it. `timeout`: the JVM was killed after
        `timeout_s`. `error`: the JVM is missing, crashed, or answered out of step.
        """
        cleaned = {name: " ".join(name.split()) for name in names}
        batch = list(dict.fromkeys(clean for clean in cleaned.values() if clean))
        outcome = _lookup(batch, timeout_s) if batch else {}
        return {
            name: _resolution(name, *outcome.get(clean, _NOT_FOUND))
            for name, clean in cleaned.items()
        }


def _resolution(query: str, status: _Status, smiles: str | None) -> Resolution:
    ids = {"smiles": smiles} if smiles else {}
    return Resolution(query, "iupac", smiles, ids, "opsin", status)
