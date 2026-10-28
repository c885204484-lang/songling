import calendar
from unittest.mock import patch

import pytest

from libnmea_navsat_driver.serial_buffer import NMEABuffer
from libnmea_navsat_driver.parser import convert_time


def frame(body):
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f'${body}*{checksum:02X}\r\n'.encode()


def test_split_chunks_preserve_complete_sentences():
    data = frame('GNGGA,120000.25,old')
    buffer = NMEABuffer()
    assert buffer.feed(data[:9]) == []
    assert buffer.feed(data[9:] + b'$GPH') == [data.decode().strip()]
    assert buffer.pending == b'$GPH'


def test_backlog_keeps_latest_valid_epoch_of_each_type_in_order():
    buffer = NMEABuffer()
    old = frame('GNGGA,120000.00,old')
    gst = frame('GNGST,120003.00,error')
    new = frame('GNGGA,120003.00,new')
    heading = frame('GPHDT,12.0,T')
    invalid = b'$GNGGA,120004.00,broken*00\r\n'
    assert buffer.feed(old*1000 + gst + new + heading + invalid) == [
        x.decode().strip() for x in (gst, new, heading)]


def test_binary_noise_and_unterminated_input_are_bounded():
    buffer = NMEABuffer()
    assert buffer.feed(b'\xff'*100000) == []
    assert len(buffer.pending) == 65536
    valid = frame('GPHDT,0.0,T')
    assert buffer.feed(b'\n\x99\xff'+valid) == [valid.decode().strip()]


@pytest.mark.parametrize('utc,now,expected', [
    ('120000.125', '12:00:01', '12:00:00'),
    ('235959.125', '00:00:01', '23:59:59'),
    ('000000.125', '23:59:59', '00:00:00'),
])
def test_measurement_time_preserves_fraction_and_nearest_day(utc, now, expected):
    import time
    epoch = calendar.timegm(time.strptime('2026-10-27 '+now, '%Y-%m-%d %H:%M:%S'))
    with patch('libnmea_navsat_driver.parser.time.time', return_value=epoch):
        value = convert_time(utc)
    assert value % 1 == pytest.approx(.125)
    assert time.strftime('%H:%M:%S', time.gmtime(value)) == expected
    assert abs(value-epoch) < 2
