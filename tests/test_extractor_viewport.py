import numpy as np
import pytest

from recoil_processor.run_extractor import Viewport


@pytest.mark.parametrize("zoom,cx,cy", [(1, 100, 80), (4, 65.25, 55.5), (0.5, 100, 80)])
def test_rendered_point_matches_marker_mapping(zoom, cx, cy):
    image = np.zeros((160, 200, 3), dtype=np.uint8)
    image[55:58, 65:68] = 255
    view = Viewport(200, 160, 300, 234)
    view.zoom, view.cx, view.cy = zoom, cx, cy
    frame = view.render(image)
    sx, sy = view.i2s(66, 56)
    assert frame[sy, sx].max() > 0
    ix, iy = view.s2i(sx, sy)
    assert abs(ix - 66) <= 0.5 / zoom
    assert abs(iy - 56) <= 0.5 / zoom


def test_zoom_keeps_image_point_under_cursor_away_from_edges():
    view = Viewport(2000, 1600, 800, 634)
    view.zoom = 1
    before = view.s2i(250, 210)
    view.zoom_at(250, 210)
    assert view.s2i(250, 210) == pytest.approx(before)


def test_letterboxed_image_remains_centered_when_clamped():
    view = Viewport(200, 100, 1000, 834)
    view.fit()
    view.pan(500, 500)
    assert view.cx == 100
    assert view.cy == 50