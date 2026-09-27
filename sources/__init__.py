"""Facility-registry adapters.

SATAT cross-checks every thermal detection against four independent
registries. Each adapter in this package turns one upstream dataset into the
same normalized facility table (see ``sources.schema``), so the rest of the
pipeline never has to know which registry a row came from.
"""

from sources import eog, gem, osm, wri

# Registration order is display order in the dashboard's source filter.
ADAPTERS = [osm, wri, gem, eog]

__all__ = ["ADAPTERS", "osm", "wri", "gem", "eog"]
