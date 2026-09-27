"""SATAT analysis package.

The pipeline used to be a chain of thirteen scripts that each rewrote
``firms_final.csv``, with later scripts silently overwriting columns earlier
ones had produced. This package replaces that with named stages that each take
a frame and return a frame, so the order of operations is visible and every
emitted column has exactly one author.
"""

METHOD_VERSION = "3.0"
