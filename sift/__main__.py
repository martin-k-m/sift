"""Entry point for `python -m sift`.

The installed `sift` command is the usual way in. This exists so the package
also runs from a checkout, or anywhere the console script is not on PATH, which
is most of the ways a contributor first tries it.
"""

import sys

from .cli import main

sys.exit(main())
