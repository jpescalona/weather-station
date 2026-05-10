from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
import requests

from weather_station.sender import BluetoothSender, TelegramSender


CAPTURE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sender():
    return TelegramSender(bot_token="test_token", chat_id="12345")


@pytest.fixture
def image_files(tmp_path):
    bw = tmp_path / "img_bw.png"
    thermal = tmp_path / "img_thermal.png"
    bw.write_bytes(b"\x89PNG\r\n")
    thermal.write_bytes(b"\x89PNG\r\n")
    return [bw, thermal]


class TestTelegramSenderUrl:
    def test_url_contains_token_and_method(self, sender):
        url = sender._url("sendPhoto")
        assert "test_token" in url
        assert "sendPhoto" in url


class TestTelegramSenderSend:
    def test_success_sends_all_images(self, sender, image_files):
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch("weather_station.sender.requests.post", return_value=mock_resp) as mock_post:
            result = sender.send(image_files, "NOAA 15", CAPTURE_TIME)

        assert result is True
        assert mock_post.call_count == 2

    def test_caption_contains_satellite_name(self, sender, image_files):
        mock_resp = MagicMock()
        mock_resp.ok = True
        captured_captions = []

        def capture_call(**kwargs):
            captured_captions.append(kwargs["data"]["caption"])
            return mock_resp

        with patch("weather_station.sender.requests.post", side_effect=lambda url, **kw: capture_call(**kw)):
            sender.send(image_files, "NOAA 18", CAPTURE_TIME)

        assert all("NOAA 18" in c for c in captured_captions)

    def test_caption_labels_bw_and_thermal(self, sender, image_files):
        mock_resp = MagicMock()
        mock_resp.ok = True
        captions = []

        def capture_call(**kw):
            captions.append(kw["data"]["caption"])
            return mock_resp

        with patch("weather_station.sender.requests.post", side_effect=lambda url, **kw: capture_call(**kw)):
            sender.send(image_files, "NOAA 15", CAPTURE_TIME)

        assert "B&N" in captions[0]
        assert "Realce térmico" in captions[1]

    def test_returns_false_on_api_error(self, sender, image_files):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        with patch("weather_station.sender.requests.post", return_value=mock_resp):
            result = sender.send(image_files, "NOAA 15", CAPTURE_TIME)

        assert result is False

    def test_returns_false_on_network_error(self, sender, image_files):
        with patch("weather_station.sender.requests.post", side_effect=requests.ConnectionError):
            result = sender.send(image_files, "NOAA 15", CAPTURE_TIME)
        assert result is False

    def test_skips_missing_images(self, sender, tmp_path):
        missing = tmp_path / "missing.png"
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch("weather_station.sender.requests.post", return_value=mock_resp) as mock_post:
            result = sender.send([missing], "NOAA 15", CAPTURE_TIME)

        mock_post.assert_not_called()
        assert result is True

    def test_empty_image_list_returns_true(self, sender):
        result = sender.send([], "NOAA 15", CAPTURE_TIME)
        assert result is True


class TestTelegramSenderSendText:
    def test_success_returns_true(self, sender):
        mock_resp = MagicMock()
        mock_resp.ok = True
        with patch("weather_station.sender.requests.post", return_value=mock_resp):
            assert sender.send_text("Hello") is True

    def test_api_error_returns_false(self, sender):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        with patch("weather_station.sender.requests.post", return_value=mock_resp):
            assert sender.send_text("Hello") is False

    def test_network_error_returns_false(self, sender):
        with patch("weather_station.sender.requests.post",
                   side_effect=requests.ConnectionError):
            assert sender.send_text("Hello") is False

    def test_request_exception_returns_false(self, sender):
        with patch("weather_station.sender.requests.post",
                   side_effect=requests.Timeout):
            assert sender.send_text("Hello") is False


class TestBluetoothSender:
    def test_send_raises_not_implemented(self):
        bt = BluetoothSender(device_address="AA:BB:CC:DD:EE:FF")
        with pytest.raises(NotImplementedError):
            bt.send([], "NOAA 15", CAPTURE_TIME)
