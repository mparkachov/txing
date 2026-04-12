from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from board import video_sender
from aws.auth import AwsCredentialSnapshot


class VideoSenderTests(unittest.TestCase):
    def test_ensure_aws_profile_falls_back_to_aws_txing_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AWS_TXING_PROFILE": "txing-service",
            },
            clear=True,
        ):
            profile = video_sender.ensure_aws_profile("AWS_TXING_PROFILE")
            self.assertEqual(os.environ["AWS_PROFILE"], "txing-service")
            self.assertEqual(os.environ["AWS_DEFAULT_PROFILE"], "txing-service")

        self.assertEqual(profile, "txing-service")

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
        self.assertFalse(hasattr(args, "ca_file"))

    def test_build_sender_environment_exports_region_and_channel_name(self) -> None:
        with patch.dict(os.environ, {"EXISTING": "value"}, clear=True):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
                credentials=AwsCredentialSnapshot(
                    access_key_id="env-access",
                    secret_access_key="env-secret",
                    session_token="env-token",
                ),
            )

        self.assertEqual(environment["EXISTING"], "value")
        self.assertEqual(environment["BOARD_VIDEO_REGION"], "eu-central-1")
        self.assertEqual(
            environment["BOARD_VIDEO_CHANNEL_NAME"],
            "txing-board-video",
        )
        self.assertEqual(environment["AWS_ACCESS_KEY_ID"], "env-access")
        self.assertEqual(environment["AWS_SECRET_ACCESS_KEY"], "env-secret")
        self.assertEqual(environment["AWS_SESSION_TOKEN"], "env-token")

    def test_build_sender_environment_does_not_inject_ca_by_default(self) -> None:
        with patch.dict(os.environ, {"EXISTING": "value"}, clear=True):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
                credentials=AwsCredentialSnapshot(
                    access_key_id="env-access",
                    secret_access_key="env-secret",
                    session_token="env-token",
                ),
            )

        self.assertNotIn("SSL_CERT_FILE", environment)
        self.assertNotIn("AWS_KVS_CACERT_PATH", environment)

    def test_build_sender_environment_strips_inherited_tls_ca_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SSL_CERT_FILE": "/custom/ca.pem",
                "AWS_KVS_CACERT_PATH": "/custom/kvs-ca.pem",
            },
            clear=True,
        ):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
                credentials=AwsCredentialSnapshot(
                    access_key_id="env-access",
                    secret_access_key="env-secret",
                    session_token="env-token",
                ),
            )

        self.assertNotIn("SSL_CERT_FILE", environment)
        self.assertNotIn("AWS_KVS_CACERT_PATH", environment)

    def test_build_sender_environment_strips_legacy_board_ca_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOARD_VIDEO_CA_FILE": "/custom/board-ca.pem",
                "TXING_BOARD_VIDEO_CA_FILE": "/custom/legacy-board-ca.pem",
            },
            clear=True,
        ):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
                credentials=AwsCredentialSnapshot(
                    access_key_id="env-access",
                    secret_access_key="env-secret",
                    session_token="env-token",
                ),
            )

        self.assertNotIn("BOARD_VIDEO_CA_FILE", environment)
        self.assertNotIn("TXING_BOARD_VIDEO_CA_FILE", environment)
        self.assertNotIn("SSL_CERT_FILE", environment)
        self.assertNotIn("AWS_KVS_CACERT_PATH", environment)

    def test_build_sender_environment_removes_profile_and_file_hints(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AWS_PROFILE": "txing",
                "AWS_DEFAULT_PROFILE": "txing",
                "AWS_SHARED_CREDENTIALS_FILE": "config/aws.credentials",
                "AWS_CONFIG_FILE": "config/aws.config",
                "AWS_SESSION_TOKEN": "stale-token",
            },
            clear=True,
        ):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
                credentials=AwsCredentialSnapshot(
                    access_key_id="env-access",
                    secret_access_key="env-secret",
                    session_token=None,
                ),
            )

        self.assertNotIn("AWS_PROFILE", environment)
        self.assertNotIn("AWS_DEFAULT_PROFILE", environment)
        self.assertNotIn("AWS_SHARED_CREDENTIALS_FILE", environment)
        self.assertNotIn("AWS_CONFIG_FILE", environment)
        self.assertNotIn("AWS_SESSION_TOKEN", environment)
        self.assertEqual(environment["AWS_ACCESS_KEY_ID"], "env-access")
        self.assertEqual(environment["AWS_SECRET_ACCESS_KEY"], "env-secret")

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
        self.assertFalse(hasattr(args, "ca_file"))

    def test_parse_args_accepts_service_environment_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOARD_VIDEO_SENDER_COMMAND": "/tmp/txing-board-kvs-master",
                "BOARD_VIDEO_READY_PATTERN": "^READY$",
                "BOARD_VIDEO_VIEWER_CONNECTED_PATTERN": "^CONNECTED$",
                "BOARD_VIDEO_VIEWER_DISCONNECTED_PATTERN": "^DISCONNECTED$",
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
        self.assertEqual(str(args.aws_shared_credentials_file), "/tmp/credentials")
        self.assertEqual(str(args.aws_config_file), "/tmp/config")
        self.assertEqual(args.ready_pattern, "^READY$")
        self.assertEqual(args.viewer_connected_pattern, "^CONNECTED$")
        self.assertEqual(args.viewer_disconnected_pattern, "^DISCONNECTED$")
        self.assertFalse(hasattr(args, "ca_file"))

    def test_build_supervisor_environment_normalizes_profile_and_paths(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AWS_TXING_PROFILE": "txing",
                "AWS_SHARED_CREDENTIALS_FILE": "config/aws.credentials",
                "AWS_CONFIG_FILE": "config/aws.config",
            },
            clear=True,
        ):
            environment = video_sender._build_supervisor_environment(
                cwd=Path("/repo"),
                aws_shared_credentials_file=None,
                aws_config_file=None,
            )

        self.assertEqual(environment["AWS_PROFILE"], "txing")
        self.assertEqual(environment["AWS_DEFAULT_PROFILE"], "txing")
        self.assertEqual(
            environment["AWS_SHARED_CREDENTIALS_FILE"],
            str((Path("/repo") / "config/aws.credentials").resolve()),
        )
        self.assertEqual(
            environment["AWS_CONFIG_FILE"],
            str((Path("/repo") / "config/aws.config").resolve()),
        )

    @patch("board.video_sender.subprocess.Popen")
    def test_video_sender_supervisor_starts_with_explicit_env_and_cwd(
        self,
        popen_mock: MagicMock,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "AWS_TXING_PROFILE": "txing",
            },
            clear=True,
        ):
            with patch("board.video_sender.Path.cwd", return_value=Path("/repo")):
                process = MagicMock()
                process.poll.return_value = None
                popen_mock.return_value = process

                supervisor = video_sender.VideoSenderSupervisor(
                    channel_name="txing-board-video",
                    viewer_url="https://ops.example.com/video",
                    region="eu-central-1",
                    sender_command="/tmp/txing-board-kvs-master",
                    aws_shared_credentials_file=Path("config/aws.credentials"),
                    aws_config_file=Path("config/aws.config"),
                )
                supervisor.start()

        kwargs = popen_mock.call_args.kwargs
        self.assertEqual(kwargs["cwd"], str(Path("/repo").resolve()))
        environment = kwargs["env"]
        self.assertEqual(environment["AWS_PROFILE"], "txing")
        self.assertEqual(environment["AWS_DEFAULT_PROFILE"], "txing")
        self.assertEqual(
            environment["AWS_SHARED_CREDENTIALS_FILE"],
            str((Path("/repo") / "config/aws.credentials").resolve()),
        )
        self.assertEqual(
            environment["AWS_CONFIG_FILE"],
            str((Path("/repo") / "config/aws.config").resolve()),
        )

    def test_video_sender_supervisor_exposes_child_pid(self) -> None:
        supervisor = video_sender.VideoSenderSupervisor(
            channel_name="txing-board-video",
            viewer_url="https://ops.example.com/video",
            region="eu-central-1",
            sender_command="/tmp/txing-board-kvs-master",
        )
        self.assertIsNone(supervisor.pid)

        process = MagicMock()
        process.pid = 4321
        supervisor._process = process

        self.assertEqual(supervisor.pid, 4321)

    @patch("board.video_sender._resolve_final_credentials")
    @patch("board.video_sender._resolve_channel_arn")
    @patch("board.video_sender.subprocess.Popen")
    def test_video_sender_process_captures_native_stderr_separately(
        self,
        popen_mock: MagicMock,
        resolve_channel_arn_mock: MagicMock,
        resolve_final_credentials_mock: MagicMock,
    ) -> None:
        resolve_channel_arn_mock.return_value = "arn:aws:kinesisvideo:eu-central-1:123:channel/test/abc"
        resolve_final_credentials_mock.return_value = AwsCredentialSnapshot(
            access_key_id="env-access",
            secret_access_key="env-secret",
            session_token="env-token",
        )

        process_mock = MagicMock()
        process_mock.pid = 9876
        process_mock.poll.side_effect = [0]
        process_mock.stdout = []
        process_mock.stderr = []
        popen_mock.return_value = process_mock

        runtime = video_sender.VideoSenderProcess(
            video_sender.VideoSenderRuntimeConfig(
                region="eu-central-1",
                channel_name="txing-board-video",
                viewer_url="https://ops.example.com/video",
                state_file=video_sender.DEFAULT_VIDEO_STATE_FILE,
                sender_command="/tmp/txing-board-kvs-master",
                assume_ready_after_seconds=0.0,
                ready_pattern=None,
                viewer_connected_pattern=None,
                viewer_disconnected_pattern=None,
            )
        )

        with self.assertRaisesRegex(RuntimeError, "video sender command exited with code 0"):
            runtime.run()

        self.assertEqual(popen_mock.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(popen_mock.call_args.kwargs["stderr"], subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
