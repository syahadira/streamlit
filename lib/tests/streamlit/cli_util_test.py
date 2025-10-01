# Copyright (c) Streamlit Inc. (2018-2022) Snowflake Inc. (2022-2025)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from streamlit.cli_util import open_browser, print_to_cli


class CliUtilTest(unittest.TestCase):
    @parameterized.expand(
        [("Linux", False, True), ("Windows", True, False), ("Darwin", False, True)]
    )
    def test_open_browser(self, os_type, webbrowser_expect, popen_expect):
        """Test web browser opening scenarios."""
        from streamlit import env_util

        env_util.IS_WINDOWS = os_type == "Windows"
        env_util.IS_DARWIN = os_type == "Darwin"
        env_util.IS_LINUX_OR_BSD = os_type == "Linux"

        with patch("streamlit.env_util.is_executable_in_path", return_value=True):
            with patch("webbrowser.open") as webbrowser_open:
                with patch("subprocess.Popen") as subprocess_popen:
                    open_browser("http://some-url")
                    assert webbrowser_expect == webbrowser_open.called
                    assert popen_expect == subprocess_popen.called

    def test_open_browser_linux_no_xdg(self):
        """Test opening the browser on Linux with no xdg installed"""
        from streamlit import env_util

        env_util.IS_LINUX_OR_BSD = True

        with patch("streamlit.env_util.is_executable_in_path", return_value=False):
            with patch("webbrowser.open") as webbrowser_open:
                with patch("subprocess.Popen") as subprocess_popen:
                    open_browser("http://some-url")
                    assert webbrowser_open.called
                    assert not subprocess_popen.called

    def test_print_to_cli_with_structured_logs_enabled(self):
        """Test that print_to_cli routes through logging when structured logs enabled."""
        from streamlit import config

        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", True, "test")

            # Mock the streamlit logger
            mock_logger = MagicMock()
            with patch("logging.getLogger", return_value=mock_logger):
                print_to_cli("Test message", fg="green", bold=True)

                # Verify message was logged through logging system
                mock_logger.info.assert_called_once()
                call_args = mock_logger.info.call_args
                assert call_args[0][0] == "Test message"
                assert call_args[1]["extra"]["cli_color"] == "green"
                assert call_args[1]["extra"]["cli_style"] == "bold"

    def test_print_to_cli_with_structured_logs_disabled(self):
        """Test that print_to_cli uses click.secho when structured logs disabled."""
        from streamlit import config

        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", False, "test")

            with patch("click.secho") as mock_secho:
                print_to_cli("Test message", fg="red")

                # Verify message was printed via click.secho
                mock_secho.assert_called_once_with("Test message", fg="red")

    def test_print_to_cli_fallback_without_click(self):
        """Test that print_to_cli falls back to print() if click not available."""
        from streamlit import config

        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", False, "test")

            # Mock click import to raise ImportError
            with patch.dict(sys.modules, {"click": None}):
                stdout_capture = StringIO()
                with patch("sys.stdout", new=stdout_capture):
                    with patch("builtins.print") as mock_print:
                        print_to_cli("Test message")
                        mock_print.assert_called_once_with("Test message", flush=True)

    def test_print_to_cli_error_handling(self):
        """Test that print_to_cli falls back to click if logging routing fails."""
        from streamlit import config

        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", True, "test")

            # Mock logging.getLogger to raise an exception
            with patch("logging.getLogger", side_effect=Exception("Test error")):
                with patch("click.secho") as mock_secho:
                    print_to_cli("Test message", fg="blue")

                    # Should fall back to click.secho
                    mock_secho.assert_called_once_with("Test message", fg="blue")
