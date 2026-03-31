from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from board import video_sender


class VideoSenderTests(unittest.TestCase):
    def test_parse_args_uses_repo_sender_marker_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "sys.argv",
                [
                    "board-video-sender",
                    "--region",
                    "eu-central-1",
                    "--viewer-url",
                    "https://ops.example.com/video",
                ],
            ):
                args = video_sender._parse_args()

        self.assertEqual(args.ready_pattern, video_sender.DEFAULT_READY_PATTERN)
        self.assertEqual(
            args.viewer_connected_pattern,
            video_sender.DEFAULT_VIEWER_CONNECTED_PATTERN,
        )
        self.assertEqual(
            args.viewer_disconnected_pattern,
            video_sender.DEFAULT_VIEWER_DISCONNECTED_PATTERN,
        )

    def test_build_sender_environment_exports_region_and_channel_name(self) -> None:
        with patch.dict(os.environ, {"EXISTING": "value"}, clear=True):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
            )

        self.assertEqual(environment["EXISTING"], "value")
        self.assertEqual(environment["BOARD_VIDEO_REGION"], "eu-central-1")
        self.assertEqual(
            environment["BOARD_VIDEO_CHANNEL_NAME"],
            "txing-board-video",
        )

    def test_build_sender_environment_prefers_explicit_board_ca_file(self) -> None:
        with patch.dict(os.environ, {"EXISTING": "value"}, clear=True):
            with patch.object(video_sender.Path, "is_file", return_value=True):
                environment = video_sender._build_sender_environment(
                    region="eu-central-1",
                    channel_name="txing-board-video",
                    ca_file=video_sender.Path("/home/user/txing/certs/AmazonRootCA1.pem"),
                )

        self.assertEqual(
            environment["BOARD_VIDEO_CA_FILE"],
            "/home/user/txing/certs/AmazonRootCA1.pem",
        )
        self.assertEqual(
            environment["SSL_CERT_FILE"],
            "/home/user/txing/certs/AmazonRootCA1.pem",
        )
        self.assertEqual(
            environment["AWS_KVS_CACERT_PATH"],
            "/home/user/txing/certs/AmazonRootCA1.pem",
        )

    def test_build_sender_environment_discovers_default_ca_bundle(self) -> None:
        with patch.dict(os.environ, {"EXISTING": "value"}, clear=True):
            with patch.object(
                video_sender,
                "DEFAULT_CA_CERT_CANDIDATES",
                (video_sender.Path("/tmp/test-ca-bundle.crt"),),
            ):
                with patch.object(video_sender.Path, "is_file", return_value=True):
                    environment = video_sender._build_sender_environment(
                        region="eu-central-1",
                        channel_name="txing-board-video",
                    )

        self.assertEqual(
            environment["SSL_CERT_FILE"],
            "/tmp/test-ca-bundle.crt",
        )
        self.assertEqual(
            environment["AWS_KVS_CACERT_PATH"],
            "/tmp/test-ca-bundle.crt",
        )

    def test_build_sender_environment_preserves_explicit_ca_env(self) -> None:
        with patch.dict(
            os.environ,
            {"SSL_CERT_FILE": "/custom/ca.pem"},
            clear=True,
        ):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
            )

        self.assertEqual(environment["SSL_CERT_FILE"], "/custom/ca.pem")
        self.assertEqual(environment["AWS_KVS_CACERT_PATH"], "/custom/ca.pem")

    def test_parse_args_accepts_explicit_aws_files(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "sys.argv",
                [
                    "board-video-sender",
                    "--region",
                    "eu-central-1",
                    "--viewer-url",
                    "https://ops.example.com/video",
                    "--aws-shared-credentials-file",
                    "/tmp/credentials",
                    "--aws-config-file",
                    "/tmp/config",
                ],
            ):
                args = video_sender._parse_args()

        self.assertEqual(str(args.aws_shared_credentials_file), "/tmp/credentials")
        self.assertEqual(str(args.aws_config_file), "/tmp/config")

    def test_parse_args_accepts_service_environment_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOARD_VIDEO_SENDER_COMMAND": "/tmp/txing-board-kvs-master",
                "BOARD_VIDEO_READY_PATTERN": "^READY$",
                "BOARD_VIDEO_VIEWER_CONNECTED_PATTERN": "^CONNECTED$",
                "BOARD_VIDEO_VIEWER_DISCONNECTED_PATTERN": "^DISCONNECTED$",
                "BOARD_VIDEO_CA_FILE": "/tmp/ca.pem",
                "AWS_SHARED_CREDENTIALS_FILE": "/tmp/credentials",
                "AWS_CONFIG_FILE": "/tmp/config",
            },
            clear=True,
        ):
            with patch(
                "sys.argv",
                [
                    "board-video-sender",
                    "--region",
                    "eu-central-1",
                    "--viewer-url",
                    "https://ops.example.com/video",
                ],
            ):
                args = video_sender._parse_args()

        self.assertEqual(args.sender_command, "/tmp/txing-board-kvs-master")
        self.assertEqual(str(args.ca_file), "/tmp/ca.pem")
        self.assertEqual(str(args.aws_shared_credentials_file), "/tmp/credentials")
        self.assertEqual(str(args.aws_config_file), "/tmp/config")
        self.assertEqual(args.ready_pattern, "^READY$")
        self.assertEqual(args.viewer_connected_pattern, "^CONNECTED$")
        self.assertEqual(args.viewer_disconnected_pattern, "^DISCONNECTED$")


if __name__ == "__main__":
    unittest.main()
