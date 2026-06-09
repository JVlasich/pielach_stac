"""Asset discovery and matching

Recursivly walk input path (reuse resolve_inputs)
Match registry.py, sorted by len(suffix+extension),
most specific first (e.g. .copc.laz before .laz).
one Item per (stem, category)
unknown_asset_policy = skip | warn (default) | raise

walk, match, group by (stem,category), sidecar association, unknown policy"""