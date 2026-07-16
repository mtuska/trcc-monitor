"""Tests for theme helpers."""
from trcc_monitor.render import theme


def test_temp_color_ramps_green_to_red():
    amax = 85
    cool = theme.temp_color(35, amax)     # well under advised max
    hot = theme.temp_color(100, amax)     # well over advised max
    assert cool == theme.ACCENT_GREEN
    assert hot == theme.ACCENT_RED


def test_temp_color_cools_monotonically():
    # The ramp passes through yellow, so the red channel isn't monotonic, but
    # the green channel should only fall as things heat up — never warm back.
    amax = 85
    greens = [theme.temp_color(t, amax)[1] for t in range(30, 101, 5)]
    assert greens == sorted(greens, reverse=True)


def test_temp_color_keys_to_advised_max():
    # The same absolute temperature reads hotter against a lower advised max,
    # so a GPU (83) flags earlier than a CPU (85) would at the same temp.
    t = 84
    cpu = theme.temp_color(t, 85)     # just under its max
    gpu = theme.temp_color(t, 83)     # just over its max
    assert gpu[0] >= cpu[0]           # GPU redder
