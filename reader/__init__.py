"""
Reader package public surface.
Importing `reader` will expose:

    from reader import make_reader
"""

from .core import make_reader          # re-export top-level API

__all__ = ["make_reader"]