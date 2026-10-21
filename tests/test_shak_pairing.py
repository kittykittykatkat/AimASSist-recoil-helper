import pytest
from recoil_processor.run_extractor import paired_midpoints, export_pattern


def test_midpoints_do_not_depend_on_pair_width():
    assert paired_midpoints([(90, 10), (110, 10), (50, 20), (150, 22)]) == [(100, 10), (100, 21)]


def test_incomplete_pair_cannot_export():
    with pytest.raises(ValueError):
        paired_midpoints([(10, 20)])


def test_shak_export_keeps_origin_interval_and_wall_scalar(tmp_path):
    path = tmp_path / "shak.txt"
    count = export_pattern(path, [(90, 20), (110, 20), (60, 40), (140, 40)],
                           100, 4.5, origin=(100, 0))
    assert count == 3
    lines = path.read_text().splitlines()
    assert lines[0] == "# interval_ms=100"
    assert [tuple(map(float, line.split(','))) for line in lines[1:]] == [(0, 0), (0, -0.9), (0, -0.9)]


def test_normal_export_remains_plain_text(tmp_path):
    path = tmp_path / "normal.txt"
    export_pattern(path, [(0, 0), (10, 20)], 100, 4.5)
    assert path.read_text() == "0.00, 0.00\n-0.45, -0.9\n"