"""group_tiles: runt tiles merge into edge-adjacent neighbors, deterministically."""
import pytest

opals = pytest.importorskip("opals")  # tac_pcl imports opals at module load

from stac.pre.tac_pcl import group_tiles


def test_no_threshold_keeps_all_tiles():
    tiles = [("a.laz", 500, (0, 0)), ("b.laz", 1, (1, 0))]
    assert group_tiles(tiles, 0) == [["a.laz"], ["b.laz"]]


def test_runt_merges_into_smallest_adjacent_tile():
    tiles = [
        ("big.laz", 500, (0, 0)),
        ("runt.laz", 1, (1, 0)),
        ("small.laz", 400, (2, 0)),
    ]
    groups = group_tiles(tiles, 100)
    assert sorted(map(len, groups)) == [1, 2]
    assert ["small.laz", "runt.laz"] in groups  # largest member first, names output
    assert ["big.laz"] in groups


def test_diagonal_is_not_adjacent():
    tiles = [("a.laz", 500, (0, 0)), ("runt.laz", 1, (1, 1))]
    assert group_tiles(tiles, 100) == [["a.laz"], ["runt.laz"]]


def test_isolated_runt_kept():
    tiles = [("a.laz", 500, (0, 0)), ("far.laz", 1, (10, 10))]
    assert group_tiles(tiles, 100) == [["a.laz"], ["far.laz"]]


def test_runt_chain_collapses_iteratively():
    # two adjacent runts pair up first, then the pair joins the big tile
    tiles = [
        ("a.laz", 300, (0, 0)),
        ("b.laz", 1, (1, 0)),
        ("c.laz", 1, (2, 0)),
    ]
    groups = group_tiles(tiles, 100)
    assert len(groups) == 1
    assert groups[0][0] == "a.laz"
    assert sorted(groups[0]) == ["a.laz", "b.laz", "c.laz"]


def test_deterministic_regardless_of_input_order():
    tiles = [
        ("a.laz", 300, (0, 0)),
        ("b.laz", 5, (1, 0)),
        ("c.laz", 400, (1, 1)),
        ("d.laz", 5, (0, 1)),
    ]
    expected = group_tiles(tiles, 100)
    assert group_tiles(list(reversed(tiles)), 100) == expected


def test_cross_footprint_leaves_no_mergeable_runt_below_threshold():
    # cross of full tiles with sliver tiles hanging off the arms
    tiles = [
        ("n.laz", 400, (1, 2)),
        ("s.laz", 400, (1, 0)),
        ("w.laz", 400, (0, 1)),
        ("e.laz", 400, (2, 1)),
        ("mid.laz", 600, (1, 1)),
        ("sliver1.laz", 2, (0, 2)),
        ("sliver2.laz", 3, (2, 0)),
        ("sliver3.laz", 1, (3, 1)),
    ]
    groups = group_tiles(tiles, 100)
    sizes = {name: size for name, size, _ in tiles}
    for g in groups:
        assert sum(sizes[n] for n in g) >= 100
        assert sizes[g[0]] == max(sizes[n] for n in g)
