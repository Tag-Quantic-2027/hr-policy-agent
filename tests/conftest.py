"""Settings for the whole test run.

Tests use keyword search, so they need no embedding model and no network.
This must be set before anything imports app.config.
"""

import os

os.environ["RETRIEVAL_MODE"] = "keyword"
