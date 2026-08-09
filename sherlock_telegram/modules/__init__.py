"""Hand-written OSINT modules.

Anything a manifest entry can express lives in ``resources/surfaces.json``.
These modules exist for the surfaces that need real parsing: entity
classification, marketplace state, feed statistics, permutation generation and
the authenticated phone lookup.
"""

from . import channel, fragment, permutations, phone, tme

__all__ = ["channel", "fragment", "permutations", "phone", "tme"]
