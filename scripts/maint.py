#!/usr/bin/env python3
"""Thin shim — delegates to starboard_skills.maint.__main__.

Usage: python scripts/maint.py <command> [options]
       (or use the 'starboard-maint' console script after installation)
"""
from __future__ import annotations

import sys

from starboard_skills.maint.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
