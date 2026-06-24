"""Boot animation module smoke tests."""
import importlib


def test_boot_anim_constants():
    meteor = importlib.import_module("boot_meteor")
    genesis = importlib.import_module("boot_genesis")
    assert meteor.DURATION >= 9.0
    assert genesis.DURATION >= 9.0
    assert meteor.FPS >= 8
    assert genesis.FPS >= 8


def test_boot_anim_common_grid():
    common = importlib.import_module("boot_anim_common")
    grid = common.make_color_grid()
    assert len(grid) == common.H
    assert len(grid[0]) == common.W
