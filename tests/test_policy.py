"""RunPolicy: the config-key <-> field bridge and the value guard."""

import pytest

from stac.catalog.policy import RunPolicy


def test_config_defaults_round_trip():
    # every key the config template generates must map back onto its field: a typo in
    # _FIELD_MAP silently drops that knob on every config-file run
    assert RunPolicy.from_config(RunPolicy.config_defaults()) == RunPolicy()


def test_from_config_reads_camel_case_and_keeps_defaults_for_absent_keys():
    p = RunPolicy.from_config({"dryRun": True, "minPoints": 5, "assetHrefs": "relative"})
    assert (p.dry_run, p.min_points, p.asset_hrefs) == (True, 5, "relative")
    assert p.stale == "warn" and p.force is False


def test_invalid_literal_rejected():
    with pytest.raises(ValueError, match="stale='nope'"):
        RunPolicy(stale="nope")
