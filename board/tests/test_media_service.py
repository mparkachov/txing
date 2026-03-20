from __future__ import annotations

import argparse
import unittest

from board.media_service import (
    DEFAULT_SIGNALLING_HOST,
    DEFAULT_SIGNALLING_PORT,
    DEFAULT_SOURCE_PIPELINE,
    DEFAULT_STREAM_NAME,
    _build_gstreamer_command,
)


class MediaServiceTests(unittest.TestCase):
    def test_default_pipeline_is_locked_to_1080p30_hardware_h264(self) -> None:
        args = argparse.Namespace(
            source_pipeline=DEFAULT_SOURCE_PIPELINE,
            stream_name=DEFAULT_STREAM_NAME,
            signalling_host=DEFAULT_SIGNALLING_HOST,
            signalling_port=DEFAULT_SIGNALLING_PORT,
        )

        command = _build_gstreamer_command(args, "gst-launch-1.0")
        command_text = " ".join(command)

        self.assertIn("libcamerasrc", command_text)
        self.assertIn("width=1920", command_text)
        self.assertIn("height=1080", command_text)
        self.assertIn("framerate=30/1", command_text)
        self.assertIn("v4l2h264enc", command_text)
        self.assertIn("run-signalling-server=true", command_text)
        self.assertIn("signalling-server-host=::", command_text)
        self.assertIn(f"signalling-server-port={DEFAULT_SIGNALLING_PORT}", command_text)


if __name__ == "__main__":
    unittest.main()
