"""PyInstaller entry for Cloudy Reader.app: the `cloudyreader` console script, frozen.

A launcher, not cloudyreader/__main__.py itself: PyInstaller runs its entry as a top-level
script, so the package must be imported normally for its own imports to resolve.
"""

import multiprocessing
import os
import sys

PROBE_ENV = "CLOUDYREADER_PROBE"


def run() -> int:
    """A build probe when build_app.sh asks for one (PROBE_ENV=engines or plan), else the app."""
    probe = os.environ.get(PROBE_ENV)
    if probe == "engines":
        from cloudyreader.engines.bundle_probe import main
    elif probe == "plan":
        from cloudyreader.engines.bundle_probe import plan_main as main
    else:
        from cloudyreader.__main__ import main
    return main()


if __name__ == "__main__":
    # A frozen child process must run its task, not open a second app.
    multiprocessing.freeze_support()
    sys.exit(run())
