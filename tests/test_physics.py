"""The sub-pixel retrieval is the one piece of real physics in the system,
so it is tested against synthetic pixels whose answer is known exactly."""

import numpy as np
import pytest
from scipy.optimize import brentq

from satat import config, physics
from satat.physics import planck_radiance as B

WL4, WL5 = config.VIIRS_I4_UM, config.VIIRS_I5_UM


def synthesize(t_fire, fraction, background=300.0):
    """Build the brightness temperatures a pixel with this fire would report."""
    l4 = fraction * B(WL4, t_fire) + (1 - fraction) * B(WL4, background)
    l5 = fraction * B(WL5, t_fire) + (1 - fraction) * B(WL5, background)
    invert = lambda wl, radiance: brentq(lambda t: B(wl, t) - radiance, 150, 4000)
    return invert(WL4, l4), invert(WL5, l5)


@pytest.mark.parametrize("t_fire,fraction", [
    (1800.0, 0.0004),    # gas flare
    (1500.0, 0.0008),    # furnace
    (1200.0, 0.002),     # hot industrial
    (750.0, 0.01),       # biomass
    (600.0, 0.04),       # smouldering
])
def test_retrieval_recovers_known_fire(t_fire, fraction):
    bt4, bt5 = synthesize(t_fire, fraction)
    retrieved_t, retrieved_p, status = physics.solve_subpixel(bt4, bt5, 300.0, 300.0, WL4, WL5)

    assert status == "ok"
    assert retrieved_t == pytest.approx(t_fire, rel=0.02)
    assert retrieved_p == pytest.approx(fraction, rel=0.05)


def test_planck_is_monotonic_in_temperature():
    temps = np.linspace(300, 2000, 50)
    radiances = [B(WL4, t) for t in temps]
    assert all(b > a for a, b in zip(radiances, radiances[1:]))


def test_no_hot_component_reports_below_background():
    _, _, status = physics.solve_subpixel(300.5, 300.0, 300.0, 300.0, WL4, WL5)
    assert status == "below_background"


def test_flat_11um_is_reported_as_unconstrained_not_guessed():
    """The failure that used to produce confident 2400 K 'flares'.

    A pixel with a strong 3.7 um signal but no 11 um excess does not
    constrain the temperature, and the retrieval must say so rather than
    return whatever the top of the search range happens to be.
    """
    temperature, fraction, status = physics.solve_subpixel(
        340.0, 300.2, 300.0, 300.0, WL4, WL5
    )
    assert status == "weak_11um"
    assert np.isnan(temperature) and np.isnan(fraction)


def test_temp_class_bands():
    assert physics.temp_class(1600) == "flare_like"
    assert physics.temp_class(1200) == "furnace_like"
    assert physics.temp_class(900) == "mixed"
    assert physics.temp_class(600) == "biomass_like"
    assert physics.temp_class(450) == "smouldering"
    assert physics.temp_class(float("nan")) == "unknown"


def test_retrieved_fraction_never_exceeds_the_pixel():
    bt4, bt5 = synthesize(700.0, 0.5)
    _, fraction, status = physics.solve_subpixel(bt4, bt5, 300.0, 300.0, WL4, WL5)
    if status == "ok":
        assert 0 < fraction <= 1.0
