#!/usr/bin/env python3
"""Compatibility entry point; public datasets share one trusted publisher."""
from publish_data import apply_and_validate, prepare, publish, main

if __name__ == '__main__':
    raise SystemExit(main())
