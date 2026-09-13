import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mach_logs.parser import LogFormatError, parse_raw_log

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "anonymized_messages.json"
EMPTY_LOG_PATH = Path(__file__).parent / "fixtures" / "empty.bin"


class FakeMessage:
    def __init__(self, values):
        self._type = values.pop("type")
        self._fieldnames = list(values)
        for name, value in values.items():
            setattr(self, name, value)

    def get_type(self):
        return self._type


class FakeLog:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.closed = False

    def recv_match(self, **_kwargs):
        return next(self.messages, None)

    def close(self):
        self.closed = True


def load_fixture():
    values = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return [FakeMessage(item) for item in values]


def test_parse_raw_log_uses_one_connection_and_builds_expected_frames():
    fake_log = FakeLog(load_fixture())

    with patch("mach_logs.parser.mavutil.mavlink_connection", return_value=fake_log) as connect:
        frames = parse_raw_log(EMPTY_LOG_PATH, 48.0, -3.0)

    connect.assert_called_once_with(str(EMPTY_LOG_PATH))
    assert fake_log.closed
    assert set(frames) == {"GPS", "ATT", "POS"}
    assert list(frames["GPS"]["Time"]) == [1.0, 2.0]
    assert frames["GPS"].loc[0, "Spd_3D"] == pytest.approx(10.198039)
    assert frames["GPS"].loc[0, "X"] == pytest.approx(0.0)


def test_parse_raw_log_rejects_missing_time():
    fake_log = FakeLog([FakeMessage({"type": "GPS", "Lat": 48.0, "Lng": -3.0})])

    with patch("mach_logs.parser.mavutil.mavlink_connection", return_value=fake_log):
        with pytest.raises(LogFormatError, match="missing TimeUS"):
            parse_raw_log(EMPTY_LOG_PATH, 48.0, -3.0)

    assert fake_log.closed
