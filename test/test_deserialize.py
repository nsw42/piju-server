import pytest
from pijuv2.backend.deserialize import extract_id, extract_ids, parse_bool


@pytest.mark.parametrize('testval', ['', '/albums/12X', 'cat'])
def test_extract_id_illegal_values_return_none(testval):
    assert extract_id(testval) is None


@pytest.mark.parametrize("testval, expected",
                         [('/albums/85', 85),
                          ('/tracks/123', 123),
                          ('234', 234),
                          (432, 432)])
def test_extract_id(testval, expected):
    assert extract_id(testval) == expected


def test_extract_ids():
    assert extract_ids(['/tracks/345', '456', 567]) == [345, 456, 567]


@pytest.mark.parametrize("testval, expected",
                         [('yes', True),
                          ('y', True),
                          ('Y', True),
                          ('True', True),
                          ('False', False),
                          ('XYZ', False)])
def test_parse_bool_yes(testval, expected):
    assert parse_bool(testval) == expected
