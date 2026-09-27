# Legacy pipeline (v2)

These are the scripts the college-demo build ran: a chain of thirteen steps
that each rewrote `firms_final.csv` in place, with later steps silently
overwriting columns earlier ones had produced. `add_risk_score_v2.py` computed
a `risk_score`, then `fix_priority_formula.py` replaced it; `fusion_model_v2.py`
assigned `final_label`, then `fix_classification_logic.py` and `reclassify_v3.py`
each reassigned it again.

They are kept for provenance — the v3 results should be comparable to what the
earlier demo produced, and that is easier to check with the old code present
than with it deleted.

**Nothing in the current pipeline imports from here.** The replacement is the
`satat/` package, where each stage takes a frame and returns a frame and every
emitted column has exactly one author. See the repository README.

Still live at the repository root:

- `fetch_data_v3.py` — NASA FIRMS pull
- `clean_detections.py` — confidence filter, India clip, cross-sensor dedup
- `build_india_boundary.py` — builds the boundary `clean_detections.py` clips to
- `build_registry.py`, `run_analysis.py`, `evaluate.py`, `run_pipeline.py`
