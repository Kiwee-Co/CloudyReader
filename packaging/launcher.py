"""PyInstaller entry for Cloudy Reader.app: the `cloudyreader` console script, frozen.

A launcher, not cloudyreader/__main__.py itself: PyInstaller runs its entry as a top-level
script, so the package must be imported normally for its own imports to resolve.
"""

import multiprocessing
import os
import sys

PROBE_ENV = "CLOUDYREADER_PROBE"


def run() -> int:
    """The engine import probe when the build asks for it (PROBE_ENV=engines), else the app."""
    if os.environ.get(PROBE_ENV) == "engines":
        from cloudyreader.engines.bundle_probe import main
    else:
        from cloudyreader.__main__ import main
    return main()


if __name__ == "__main__":
    # A frozen child process must run its task, not open a second app.
    multiprocessing.freeze_support()
    sys.exit(run())
