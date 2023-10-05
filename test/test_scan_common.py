import datetime
import pytest

from pijuv2.scan.common import parse_datetime_str


@pytest.mark.parametrize("datetimestr, expected",
                         [('1994', datetime.datetime(1994, 1, 1, 0, 0)),
                          ('2021-09', datetime.datetime(2021, 9, 1, 0, 0)),
                          ('1997-05-12', datetime.datetime(1997, 5, 12, 0, 0)),
                          ('2001-12-31T23:29:59Z', datetime.datetime(2001, 12, 31, 23, 29, 59)),
                          ('2001-12-31 23:29:59Z', datetime.datetime(2001, 12, 31, 23, 29, 59)),
                          ('2001-12-31T23:29:59', datetime.datetime(2001, 12, 31, 23, 29, 59)),
                          ('2001-12-31T23:29:59PDT', datetime.datetime(2001, 12, 31, 23, 29, 59)),
                          ('2015-07-15T16:54:33+0100', datetime.datetime(2015, 7, 15, 16, 54, 33)),
                          ('2016-08-29T21:32:06-0700', datetime.datetime(2016, 8, 29, 21, 32, 6))])
def test_parse_datetime_str(datetimestr, expected):
    assert parse_datetime_str(datetimestr) == expected


@pytest.mark.parametrize("malformed_str",
                         ['Some point in the 21st Century',
                          '1994-01-01-01-01-01',
                          '1994 bottles of beer on the wall'])
def test_malformed_values_raise_value_error(malformed_str):
    with pytest.raises(ValueError, match='malformed date: ' + str(malformed_str)):
        parse_datetime_str(malformed_str)
