#!/usr/bin/env python3
"""Thin entrypoint so the project runs with `python run.py ...`.

Equivalent to `python -m wealth_advisor`.
"""

import sys

from wealth_advisor.cli import main

if __name__ == "__main__":
    sys.exit(main())
