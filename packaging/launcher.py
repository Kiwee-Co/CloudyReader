"""PyInstaller entry for Cloudy Reader.app: the `cloudyreader` console script, frozen.

A launcher, not cloudyreader/__main__.py itself: PyInstaller runs its entry as a top-level
script, so the package must be imported normally for its own imports to resolve.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    # A frozen child process must run its task, not open a second app.
    multiprocessing.freeze_support()
    from cloudyreader.__main__ import main

    sys.exit(main())
