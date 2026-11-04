"""Entry point for the packaged app (PyInstaller needs a plain script)."""

import sys

from photoimporter.ui.app import main

sys.exit(main())
