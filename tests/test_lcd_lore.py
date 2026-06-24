"""Lore animation scheduler tests."""
import importlib
import time


def test_lore_scenes_defined():
    lore = importlib.import_module("zealot_lcd_lore")
    assert "battle" in lore.SCENES
    assert "realm" in lore.SCENES
    assert lore.MIN_RANDOM_SEC <= lore.MAX_RANDOM_SEC


def test_lore_scheduler_random_pick():
    lore = importlib.import_module("zealot_lcd_lore")
    sched = lore.LoreAnimScheduler()
    sched.next_random = time.time() - 1
    sched.cooldown_until = 0
    scene = sched.pick_scene({"bridge": {}}, time.time())
    assert scene in lore.RANDOM_POOL
