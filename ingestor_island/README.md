# ingestor_island

Ingestion and diagnostics island for data inspection.

## Scope
- detect source format and inspect structure
- profile tabular-like data
- run vital diagnostics
- emit assumptions JSON for downstream systems
- emit `diagnostic_bundle.v1` JSON for the recommender island

## Current code location
- Active implementation lives at: `ingestor_island/src/data_inspector`
- Entry wrapper: `inspect_data.py`
- Compatibility shim for legacy imports: `src/data_inspector`

## Example
```bash
python3 inspect_data.py sample_data/train_data_random.npz \
  --diagnostic-bundle-out tmp/diagnostic_bundle.json
```

This island directory is the ownership boundary for ingestion concerns as the codebase transitions to a full 3-island layout.
