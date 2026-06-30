# CLI / Config resolver   (cli.py + config.py)
#         │ project.yml (nested) + flat knobs + CLI overrides
#         ▼
# Layer 1  Discovery + Extraction   (discovery.py, registry.py, extract.py)
#    walk → matcher → (label, category, kind, roles, media_type, extensions)
#    group by (stem, category); associate sidecars by full basename
#    @reader(kind) does I/O once → AssetMeta; @populator(ext) maps AssetMeta → pystac
#         ▼
# Layer 2  Item + Collection builder   (build.py, hierarchy.py)
#    one Item per (stem, category); enable extensions; build ids/datetime/geometry
#    placement resolver: Item → placement-path in the tree
#         ▼
# Layer 3  Catalog manager   (manager.py)
#    load existing (extend mode) → merge by id → recompute extents/summaries → write