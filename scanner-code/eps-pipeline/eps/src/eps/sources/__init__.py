"""Shared collection layer for non-GOV.UK sources.

The UK harvester talks to one API with one document shape. The US side has 24
agencies with 24 site shapes, so the parts that must not vary between them --
HTML-to-text conversion, the block model, the adapter contract -- live here and
are inherited rather than reimplemented per agency.

Nothing in this package knows about the UK pipeline, and nothing in the UK
pipeline imports from it.
"""
