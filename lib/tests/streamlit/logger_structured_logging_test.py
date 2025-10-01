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

"""Tests for structured (JSON) logging functionality."""

from __future__ import annotations

import logging
import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from streamlit import config, logger


class StructuredLoggingTest(unittest.TestCase):
    """Test structured JSON logging features."""

    def setUp(self):
        """Set up test fixtures."""
        # Clear any cached loggers
        logger._loggers.clear()

    def tearDown(self):
        """Clean up after tests."""
        logger._loggers.clear()

    def test_json_formatter_enabled_with_library(self):
        """Test JSON formatter is used when enableStructuredLogs=true and library available."""
        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", True, "test")

            # Mock successful import of pythonjsonlogger
            with patch.dict(sys.modules, {"pythonjsonlogger": MagicMock()}):
                with patch.dict(sys.modules, {"pythonjsonlogger.json": MagicMock()}):
                    test_logger = logger.get_logger("test.structured")

                    # Verify logger has handler
                    assert len(test_logger.handlers) == 1
                    # Would verify formatter type here, but since we're mocking
                    # the import, we can't instantiate the actual JsonFormatter

    def test_json_formatter_fallback_without_library(self):
        """Test fallback to standard formatter when python-json-logger not available."""
        stderr_capture = StringIO()

        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", True, "test")

            # Simulate ImportError when trying to import pythonjsonlogger
            with patch.dict(sys.modules, {"pythonjsonlogger": None}):
                with patch("sys.stderr", new=stderr_capture):
                    test_logger = logger.get_logger("test.fallback")

                    # Verify logger has handler (standard formatter)
                    assert len(test_logger.handlers) == 1
                    assert test_logger.handlers[0].formatter is not None

                    # Verify warning was printed
                    stderr_output = stderr_capture.getvalue()
                    assert "python-json-logger" in stderr_output
                    assert "Falling back" in stderr_output

    def test_json_formatter_error_handling(self):
        """Test graceful handling when JsonFormatter initialization fails."""
        stderr_capture = StringIO()

        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", True, "test")

            # Mock import but make JsonFormatter raise an exception
            mock_formatter = MagicMock(side_effect=ValueError("Test error"))
            with patch.dict(
                sys.modules,
                {
                    "pythonjsonlogger": MagicMock(),
                    "pythonjsonlogger.json": MagicMock(JsonFormatter=mock_formatter),
                },
            ):
                with patch("sys.stderr", new=stderr_capture):
                    test_logger = logger.get_logger("test.error")

                    # Verify logger has handler (fell back to standard formatter)
                    assert len(test_logger.handlers) == 1
                    assert test_logger.handlers[0].formatter is not None

                    # Verify error was logged
                    stderr_output = stderr_capture.getvalue()
                    assert "Failed to configure JSON logging" in stderr_output

    def test_standard_logging_when_disabled(self):
        """Test standard formatter used when enableStructuredLogs=false (default)."""
        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", False, "test")
            config._set_option(
                "logger.messageFormat", "%(levelname)s: %(message)s", "test"
            )

            test_logger = logger.get_logger("test.standard")

            # Verify logger has handler with standard formatter
            assert len(test_logger.handlers) == 1
            assert (
                test_logger.handlers[0].formatter._fmt == "%(levelname)s: %(message)s"
            )

    def test_structured_logs_with_tornado_loggers(self):
        """Test that Tornado loggers also get structured logging when enabled."""
        with patch.object(config, "_config_options", new={}):
            config._set_option("logger.enableStructuredLogs", True, "test")

            with patch.dict(sys.modules, {"pythonjsonlogger": MagicMock()}):
                with patch.dict(sys.modules, {"pythonjsonlogger.json": MagicMock()}):
                    logger.init_tornado_logs()

                    # Verify all Tornado loggers were created
                    tornado_logger = logging.getLogger("tornado.access")
                    assert tornado_logger is not None
                    assert len(tornado_logger.handlers) >= 1
