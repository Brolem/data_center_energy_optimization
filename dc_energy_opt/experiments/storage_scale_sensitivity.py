"""Temporary compatibility import for the paper-track migration."""

import sys

from experiments.paper.houston_2020.sensitivity import (
    storage_scale as _implementation,
)

sys.modules[__name__] = _implementation
