import os

# Headless Qt for every test: no window ever opens. Override from the shell if needed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
