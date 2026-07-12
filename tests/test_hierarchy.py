from types import SimpleNamespace

from stac.catalog.hierarchy import resolve_hierarchy


def _p(pid, group=None):
    return SimpleNamespace(id=pid, group=group)


def _products():
    return [
        _p("flat_a"), _p("flat_b"),
        _p("tile_1", "tiles"), _p("tile_2", "tiles"),
        _p("stray"),
    ]


HIER = {
    "placement": {"stray": "tiles", "tile_2": None, "ghost": "tiles"},
    "groups": {"tiles": {"title": "Tile group"}, "unused": {"title": "x"}},
}


def test_flat_node_first_holds_flats_and_force_flattened():
    nodes = resolve_hierarchy(_products(), HIER)
    assert nodes[0].name is None
    assert {p.id for p in nodes[0].products} == {"flat_a", "flat_b", "tile_2"}


def test_pinned_stray_joins_group_with_metadata():
    nodes = resolve_hierarchy(_products(), HIER)
    tiles = {n.name: n for n in nodes}["tiles"]
    assert {p.id for p in tiles.products} == {"tile_1", "stray"}
    assert tiles.title == "Tile group"


def test_unused_group_dropped_unknown_placement_only_warned():
    nodes = resolve_hierarchy(_products(), HIER)
    assert {n.name for n in nodes} == {None, "tiles"}


def test_no_hierarchy_block_auto_groups_pass_through():
    nodes = resolve_hierarchy(_products())
    assert {p.id for p in nodes[1].products} == {"tile_1", "tile_2"}
