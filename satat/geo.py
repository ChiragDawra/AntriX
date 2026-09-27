"""Spatial helpers.

The original pipeline computed nearest-facility distance with a Python loop
over 16 299 OSM points for every one of 432 detections. That is 7M haversine
calls in interpreted Python for the demo dataset, and it scales quadratically
with both inputs -- unusable once the registry grew to 20 000 records across
four sources. A BallTree on the haversine metric does the same work in one
vectorised query.
"""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance, vectorised over numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


class NearestFacility:
    """Nearest-neighbour index over one registry's facilities."""

    def __init__(self, lats, lons, payload=None):
        from sklearn.neighbors import BallTree

        self.lats = np.asarray(lats, dtype=float)
        self.lons = np.asarray(lons, dtype=float)
        self.payload = list(payload) if payload is not None else None
        self.empty = len(self.lats) == 0

        if not self.empty:
            coords = np.radians(np.column_stack([self.lats, self.lons]))
            self.tree = BallTree(coords, metric="haversine")

    def query(self, lats, lons):
        """Return (distance_km, index) arrays for each query point.

        Distances are ``inf`` and indices ``-1`` when the registry is empty,
        so a source that failed to load propagates as "no evidence" rather
        than as a crash or, worse, as a zero distance.
        """
        lats = np.asarray(lats, dtype=float)
        if self.empty:
            return np.full(len(lats), np.inf), np.full(len(lats), -1)

        coords = np.radians(np.column_stack([lats, np.asarray(lons, dtype=float)]))
        dist, idx = self.tree.query(coords, k=1)
        return dist[:, 0] * EARTH_RADIUS_KM, idx[:, 0]

    def count_within(self, lats, lons, radius_km):
        """How many facilities sit within ``radius_km`` of each query point."""
        lats = np.asarray(lats, dtype=float)
        if self.empty:
            return np.zeros(len(lats), dtype=int)

        coords = np.radians(np.column_stack([lats, np.asarray(lons, dtype=float)]))
        neighbours = self.tree.query_radius(coords, r=radius_km / EARTH_RADIUS_KM)
        return np.array([len(n) for n in neighbours], dtype=int)
