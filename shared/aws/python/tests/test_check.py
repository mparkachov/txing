from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from aws.check import run_service_check, validate_service_environment


class _FakeStsClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_caller_identity(self) -> dict[str, str]:
        self.calls += 1
        return {"Arn": "arn:aws:sts::123456789012:assumed-role/test/device"}


class _FakeIotClient:
    def __init__(self) -> None:
        self.describe_thing_names: list[str] = []
        self.describe_group_names: list[str] = []

    def describe_thing(self, *, thingName: str) -> dict[str, str]:
        self.describe_thing_names.append(thingName)
        return {"thingName": thingName}

    def describe_thing_group(self, *, thingGroupName: str) -> dict[str, str]:
        self.describe_group_names.append(thingGroupName)
        return {"thingGroupName": thingGroupName}


class _FakeLogsClient:
    def __init__(self) -> None:
        self.created_streams: list[tuple[str, str]] = []
        self.events: list[tuple[str, str, list[dict[str, object]]]] = []

    def create_log_stream(self, *, logGroupName: str, logStreamName: str) -> None:
        self.created_streams.append((logGroupName, logStreamName))

    def put_log_events(
        self,
        *,
        logGroupName: str,
        logStreamName: str,
        logEvents: list[dict[str, object]],
    ) -> dict[str, str]:
        self.events.append((logGroupName, logStreamName, logEvents))
        return {"nextSequenceToken": "token"}


class _FakeIotDataClient:
    def __init__(self) -> None:
        self.thing_names: list[str] = []

    def get_thing_shadow(self, *, thingName: str) -> dict[str, object]:
        self.thing_names.append(thingName)
        return {"payload": b"{}"}


class _FakeKinesisVideoClient:
    def __init__(self) -> None:
        self.channel_names: list[str] = []

    def describe_signaling_channel(self, *, ChannelName: str) -> dict[str, object]:
        self.channel_names.append(ChannelName)
        return {
            "ChannelInfo": {
                "ChannelARN": f"arn:aws:kinesisvideo:::channel/{ChannelName}",
                "ChannelStatus": "ACTIVE",
            }
        }


class _FakeRuntime:
    def __init__(self, *, endpoint: str) -> None:
        self.endpoint = endpoint
        self.sts = _FakeStsClient()
        self.iot = _FakeIotClient()
        self.logs = _FakeLogsClient()
        self.iot_data = _FakeIotDataClient()
        self.kinesisvideo = _FakeKinesisVideoClient()
        self.client_calls: list[tuple[str, str | None, dict[str, object]]] = []

    def sts_client(self) -> _FakeStsClient:
        return self.sts

    def iot_client(self) -> _FakeIotClient:
        return self.iot

    def logs_client(self) -> _FakeLogsClient:
        return self.logs

    def iot_data_endpoint(self) -> str:
        return self.endpoint

    def client(
        self,
        service_name: str,
        *,
        region_name: str | None = None,
        **kwargs: object,
    ) -> object:
        self.client_calls.append((service_name, region_name, kwargs))
        if service_name == "iot-data":
            return self.iot_data
        if service_name == "kinesisvideo":
            return self.kinesisvideo
        raise AssertionError(f"unexpected client request: {service_name}")


class AwsCheckTests(unittest.TestCase):
    def test_validate_rig_environment_accepts_profile_selector_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            shared_credentials_file = temp_path / "aws.credentials"
            shared_credentials_file.write_text("[town]\n", encoding="utf-8")
            aws_config_file = temp_path / "aws.config"
            aws_config_file.write_text("[profile rig]\n", encoding="utf-8")

            results, resolved = validate_service_environment(
                "rig",
                {
                    "AWS_REGION": "eu-central-1",
                    "AWS_RIG_PROFILE": "rig",
                    "AWS_SHARED_CREDENTIALS_FILE": str(shared_credentials_file),
                    "AWS_CONFIG_FILE": str(aws_config_file),
                    "THING_NAME": "unit-local",
                    "RIG_NAME": "rig",
                    "SPARKPLUG_GROUP_ID": "town",
                    "SPARKPLUG_EDGE_NODE_ID": "rig",
                    "CLOUDWATCH_LOG_GROUP": "/town/rig/txing",
                },
            )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(resolved["aws_region"], "eu-central-1")
        self.assertEqual(resolved["thing_name"], "unit-local")
        self.assertEqual(resolved["rig_name"], "rig")

    def test_validate_device_environment_reports_missing_values(self) -> None:
        results, _resolved = validate_service_environment(
            "device",
            {
                "AWS_REGION": "eu-central-1",
                "AWS_SHARED_CREDENTIALS_FILE": "/missing/aws.credentials",
                "AWS_CONFIG_FILE": "/missing/aws.config",
                "THING_NAME": "unit-local",
                "SCHEMA_FILE": "/missing/schema.json",
                "BOARD_VIDEO_VIEWER_URL": "",
                "BOARD_VIDEO_REGION": "eu-central-1",
                "BOARD_VIDEO_CHANNEL_NAME": "",
                "BOARD_VIDEO_SENDER_COMMAND": "",
            },
        )

        failure_messages = [result.message for result in results if not result.ok]
        self.assertIn(
            "AWS runtime profile selector missing ($AWS_PROFILE or $AWS_DEVICE_PROFILE or $AWS_TXING_PROFILE)",
            failure_messages,
        )
        self.assertIn("AWS shared credentials file missing or not a file (/missing/aws.credentials)", failure_messages)
        self.assertIn("AWS config file missing or not a file (/missing/aws.config)", failure_messages)
        self.assertIn("Shadow schema file missing or not a file (/missing/schema.json)", failure_messages)
        self.assertIn("Board video viewer URL missing ($BOARD_VIDEO_VIEWER_URL)", failure_messages)
        self.assertIn("Board video channel name missing ($BOARD_VIDEO_CHANNEL_NAME)", failure_messages)
        self.assertIn("Board video sender command missing ($BOARD_VIDEO_SENDER_COMMAND)", failure_messages)

    def test_run_rig_service_check_uses_shared_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            shared_credentials_file = temp_path / "aws.credentials"
            shared_credentials_file.write_text("[town]\n", encoding="utf-8")
            aws_config_file = temp_path / "aws.config"
            aws_config_file.write_text("[profile rig]\n", encoding="utf-8")
            runtime = _FakeRuntime(endpoint="abc123-ats.iot.eu-central-1.amazonaws.com")

            results = run_service_check(
                "rig",
                environment={
                    "AWS_REGION": "eu-central-1",
                    "AWS_RIG_PROFILE": "rig",
                    "AWS_SHARED_CREDENTIALS_FILE": str(shared_credentials_file),
                    "AWS_CONFIG_FILE": str(aws_config_file),
                    "THING_NAME": "unit-local",
                    "RIG_NAME": "rig",
                    "SPARKPLUG_GROUP_ID": "town",
                    "SPARKPLUG_EDGE_NODE_ID": "rig",
                    "CLOUDWATCH_LOG_GROUP": "/town/rig/txing",
                },
                aws_runtime=runtime,
            )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(runtime.sts.calls, 1)
        self.assertEqual(runtime.iot.describe_thing_names, ["unit-local"])
        self.assertEqual(runtime.iot.describe_group_names, ["rig"])
        self.assertEqual(len(runtime.logs.created_streams), 1)
        self.assertEqual(runtime.logs.created_streams[0][0], "/town/rig/txing")
        self.assertEqual(len(runtime.logs.events), 1)
        self.assertEqual(runtime.logs.events[0][0], "/town/rig/txing")
        self.assertIsInstance(runtime.logs.events[0][2][0]["timestamp"], int)

    def test_run_device_service_check_uses_discovered_endpoint_and_video_region(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            shared_credentials_file = temp_path / "aws.credentials"
            shared_credentials_file.write_text("[town]\n", encoding="utf-8")
            aws_config_file = temp_path / "aws.config"
            aws_config_file.write_text("[profile device]\n", encoding="utf-8")
            schema_file = temp_path / "schema.json"
            schema_file.write_text("{}", encoding="utf-8")
            runtime = _FakeRuntime(endpoint="abc123-ats.iot.eu-central-1.amazonaws.com")

            results = run_service_check(
                "device",
                environment={
                    "AWS_REGION": "eu-central-1",
                    "AWS_DEVICE_PROFILE": "device",
                    "AWS_SHARED_CREDENTIALS_FILE": str(shared_credentials_file),
                    "AWS_CONFIG_FILE": str(aws_config_file),
                    "THING_NAME": "unit-local",
                    "SCHEMA_FILE": str(schema_file),
                    "BOARD_VIDEO_VIEWER_URL": "https://example.com/video",
                    "BOARD_VIDEO_REGION": "us-east-1",
                    "BOARD_VIDEO_CHANNEL_NAME": "unit-local-board-video",
                    "BOARD_VIDEO_SENDER_COMMAND": "/tmp/bot-board-kvs-master",
                },
                aws_runtime=runtime,
            )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(runtime.sts.calls, 1)
        self.assertEqual(runtime.iot.describe_thing_names, [])
        self.assertEqual(runtime.iot_data.thing_names, ["unit-local"])
        self.assertEqual(runtime.kinesisvideo.channel_names, ["unit-local-board-video"])
        self.assertIn(
            (
                "iot-data",
                None,
                {"endpoint_url": "https://abc123-ats.iot.eu-central-1.amazonaws.com"},
            ),
            runtime.client_calls,
        )
        self.assertIn(
            ("kinesisvideo", "us-east-1", {}),
            runtime.client_calls,
        )


if __name__ == "__main__":
    unittest.main()
