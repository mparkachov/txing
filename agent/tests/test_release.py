"""Run the actual CMake packager and POSIX publication recipe without AWS."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "arn:aws:lambda:eu-central-1:123456789012:microvm-image:test-agent"

MOCK = r'''#!/usr/bin/env python3
import base64, hashlib, json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ["FIXTURE"])
args = sys.argv[1:]
def flag(name): return args[args.index(name)+1]
def emit(value): print(json.dumps(value))
def fail(message): print(message, file=sys.stderr); sys.exit(1)
mode = (root/"mode").read_text()
tool = pathlib.Path(sys.argv[0]).name
with (root/"calls.jsonl").open("a") as f: f.write(json.dumps([tool]+args)+"\n")
if tool == "just": sys.exit(0)
if tool == "gh":
    shutil.copyfile(root/"package.zip", pathlib.Path(flag("--dir"))/"txing-agent-release-linux-arm64.zip")
    sys.exit(0)
service, operation = args[:2]
if service == "s3api":
    key = root/"s3"/flag("--key")
    if operation == "put-object":
        assert flag("--if-none-match") == "*"
        if key.exists(): fail("PreconditionFailed")
        key.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(flag("--body"), key)
        emit({"VersionId":"immutable-object-version"})
    elif operation == "get-object":
        if mode == "receipt-denied" and key.name == "built.json": fail("AccessDenied")
        if not key.exists(): fail("NoSuchKey")
        shutil.copyfile(key, args[-1]); emit({})
    else: fail("unexpected S3 operation")
elif service == "cloudformation":
    state = json.loads((root/"stack.json").read_text())
    if operation == "describe-stacks": emit({"Stacks":[state]})
    elif operation == "update-stack":
        if mode == "selection-denied": fail("AccessDenied")
        assert "--use-previous-template" in args
        parameters = json.loads(pathlib.Path(flag("--parameters")[7:]).read_text())
        for item in parameters:
            if not item.get("UsePreviousValue"):
                next(p for p in state["Parameters"] if p["ParameterKey"]==item["ParameterKey"])["ParameterValue"] = item["ParameterValue"]
        state["StackStatus"] = "UPDATE_COMPLETE"
        (root/"stack.json").write_text(json.dumps(state)); emit({"StackId":state["StackId"]})
    elif operation == "wait": pass
    else: fail("unexpected stack operation")
elif service == "lambda-microvms":
    if operation == "list-managed-microvm-image-versions": emit({"items":[{"imageVersion":"2.0","status":"EXPIRED" if mode=="expired-base" else "AVAILABLE"}]})
    elif operation in ("create-microvm-image", "update-microvm-image"):
        request = json.loads(pathlib.Path(flag("--cli-input-json")[7:]).read_text())
        (root/"request.json").write_text(json.dumps(request))
        emit({"imageArn":os.environ["IMAGE"],"imageVersion":"3.0"})
    elif operation == "get-microvm-image-version":
        if mode == "poll-unavailable": fail("RequestTimeout")
        request = json.loads((root/"request.json").read_text())
        request.update(imageArn=os.environ["IMAGE"],imageVersion="3.0",state="FAILED" if mode=="failed-build" else "SUCCESSFUL",status="INACTIVE" if mode=="inactive-build" else "ACTIVE")
        if mode == "wrong-artifact": request["codeArtifact"]["uri"] = "s3://other/other.zip"
        emit(request)
    elif operation == "get-microvm-image": emit({"imageArn":os.environ["IMAGE"],"state":"UPDATED"})
    else: fail("unexpected image operation")
elif service == "lambda" and operation == "get-function-configuration":
    value = (root/"s3/agent/1.2.3/controller.zip").read_bytes()
    emit({"CodeSha256":base64.b64encode(hashlib.sha256(value).digest()).decode()})
else: fail("unexpected AWS operation")
'''


class AgentReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="agent-release-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / "stage"
        self.source = self.root / "source"
        for path, content in {
            "runtime/txing/txing-agent": "test-only binary fixture",
            "runtime/txing/ctest.txt": "100% tests passed",
            "runtime/snapsafe/libssl.so.3": "ssl fixture",
            "runtime/snapsafe/libcrypto.so.3": "crypto fixture",
            "controller/bootstrap": "controller fixture",
            "controller/provenance/runtime-links.txt": "validated fixture",
            "controller/provenance/bootstrap-smoke.txt": "Lambda runtime API address is invalid",
        }.items():
            target = self.stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.source.mkdir()
        for name, content in {
            "source.tar": "source fixture", "source-sha256.txt": "hash fixture",
            "source-revision.txt": "a" * 40, "source-status.txt": "",
            "build-id.txt": "b" * 64, "container-base.txt": "example@sha256:" + "c" * 64,
            "physical-acceptance.md": "recorded operator decision",
        }.items():
            (self.source / name).write_text(content)
        for src, dest in (("agent/cloud/Release.Dockerfile", "Release.Dockerfile"),
                          ("agent/probe/hooks.json", "hooks.json"), ("agent/stack.yaml", "stack.yaml")):
            shutil.copyfile(ROOT / src, self.source / dest)
        self.package()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("aws", "gh", "just"):
            path = self.bin / name
            path.write_text(MOCK)
            path.chmod(0o755)
        (self.root / "mode").write_text("success")
        self.initial_parameters = {
            "ControllerBucket": "old-bucket", "ControllerKey": "old.zip",
            "ImageName": "test-agent", "ImageVersion": "2.0", "Release": "1.0.0",
            "AutomationEnabled": "true", "PrerequisitesConfirmed": "true",
            "LifecycleRuleName": "test_agent_lifecycle",
        }
        state = {
            "StackId": "arn:aws:cloudformation:eu-central-1:123456789012:stack/test-agent/uuid",
            "StackStatus": "UPDATE_COMPLETE",
            "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in self.initial_parameters.items()],
            "Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in {
                "ArtifactBucket": "artifact-bucket", "BuildRoleArn": "arn:aws:iam::123456789012:role/build",
                "LogGroup": "/aws/lambda-microvms/test-agent", "ControllerArn": "controller-function",
            }.items()],
        }
        (self.root / "stack.json").write_text(json.dumps(state))

    def package(self, label="one"):
        path = self.root / label / "package"
        result = subprocess.run([
            "cmake", f"-DSTAGE_DIR={self.stage}", f"-DSOURCE_DIR={self.source}",
            f"-DPACKAGE_DIR={path}", "-DVERSION=1.2.3", "-P", str(ROOT / "agent/cmake/Release.cmake"),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = path.parent / "txing-agent-release-linux-arm64.zip"
        shutil.copyfile(archive, self.root / "package.zip")
        return archive

    def publish(self, mode="success", version="1.2.3"):
        (self.root / "mode").write_text(mode)
        recipe = (ROOT / "agent/justfile").read_text().split("publish version:\n", 1)[1]
        recipe = textwrap.dedent(recipe.split("\n# Operator-run initial", 1)[0])
        recipe = recipe.replace("{{project_root}}", str(ROOT))
        script = self.root / "publish.sh"
        script.write_text(recipe)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "FIXTURE": str(self.root),
               "IMAGE": IMAGE, "TMPDIR": str(self.root), "TXING_AWS_STACK": "test",
               "TXING_AGENT_BASE_IMAGE_VERSION": "2.0"}
        return subprocess.run(["sh", str(script), version], env=env, text=True, capture_output=True)

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def parameters(self):
        return {p["ParameterKey"]: p["ParameterValue"] for p in json.loads((self.root / "stack.json").read_text())["Parameters"]}

    def test_archives_repeat_and_include_frozen_binaries_and_provenance(self):
        first = self.package("first").read_bytes()
        os.utime(self.stage / "controller/bootstrap", (1234567890, 1234567890))
        second = self.package("second").read_bytes()
        self.assertEqual(first, second)
        with zipfile.ZipFile(self.root / "package.zip") as archive:
            release = json.loads(archive.read("release.json"))
            self.assertTrue(release["clean"])
            for name, expected in release["files"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
        with zipfile.ZipFile(self.root / "one/package/microvm.zip") as archive:
            self.assertEqual(archive.read("runtime/txing/txing-agent"), b"test-only binary fixture")
            self.assertNotIn(b"dnf", archive.read("Dockerfile"))

    def test_success_selects_exact_image_and_preserves_launch_gates(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        params = self.parameters()
        self.assertEqual(params["Release"], "1.2.3")
        self.assertEqual(params["ImageVersion"], "3.0")
        self.assertEqual(params["ControllerKey"], "agent/1.2.3/controller.zip")
        for name in ("AutomationEnabled", "PrerequisitesConfirmed", "LifecycleRuleName"):
            self.assertEqual(params[name], self.initial_parameters[name])
        operations = [call[1:3] for call in self.calls() if call[0] == "aws"]
        self.assertNotIn(["lambda-microvms", "run-microvm"], operations)
        self.assertNotIn(["lambda-microvms", "terminate-microvm"], operations)
        self.assertTrue((self.root / "s3/agent/1.2.3/built.json").exists())

    def test_failure_never_changes_selection(self):
        for mode in ("failed-build", "inactive-build", "wrong-artifact", "expired-base", "receipt-denied"):
            with self.subTest(mode=mode):
                result = self.publish(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.parameters(), self.initial_parameters)
        self.assertFalse(any(call[1:3] == ["cloudformation", "update-stack"] for call in self.calls()))

    def test_retry_reuses_successful_receipt_without_another_build(self):
        for _ in range(2):
            result = self.publish()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        builds = [call for call in self.calls() if call[1:3] == ["lambda-microvms", "update-microvm-image"]]
        self.assertEqual(len(builds), 1)

    def test_interrupted_build_reuses_identical_request_token(self):
        self.assertNotEqual(self.publish("poll-unavailable").returncode, 0)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        builds = [call for call in self.calls() if call[1:3] == ["lambda-microvms", "update-microvm-image"]]
        self.assertEqual(len(builds), 2)
        tokens = [call[call.index("--client-token") + 1] for call in builds]
        self.assertEqual(tokens[0], tokens[1])

    def test_selection_failure_can_retry_successful_build_without_rebuilding(self):
        result = self.publish("selection-denied")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.parameters(), self.initial_parameters)
        self.assertTrue((self.root / "s3/agent/1.2.3/built.json").exists())
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sum(call[1:3] == ["lambda-microvms", "update-microvm-image"] for call in self.calls()), 1)

    def test_conflicting_s3_content_stops_before_build(self):
        conflict = self.root / "s3/agent/1.2.3/microvm.zip"
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b"different immutable content")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Immutable S3 object conflicts", result.stderr)
        self.assertEqual(conflict.read_bytes(), b"different immutable content")
        self.assertEqual(self.parameters(), self.initial_parameters)

    def test_dirty_release_stops_before_aws(self):
        (self.source / "source-status.txt").write_text(" M agent/src/main.cpp\n")
        self.package("dirty")
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertFalse(any(call[0] == "aws" for call in self.calls()))

    def test_initial_publication_creates_image_and_preserves_disabled_gates(self):
        path = self.root / "stack.json"
        state = json.loads(path.read_text())
        for parameter in state["Parameters"]:
            if parameter["ParameterKey"] == "ImageName": parameter["ParameterValue"] = "disabled"
            if parameter["ParameterKey"] in ("AutomationEnabled", "PrerequisitesConfirmed"): parameter["ParameterValue"] = "false"
        path.write_text(json.dumps(state))
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any(call[1:3] == ["lambda-microvms", "create-microvm-image"] for call in self.calls()))
        self.assertEqual(self.parameters()["AutomationEnabled"], "false")

    def test_invalid_version_stops_before_download(self):
        for version in ("latest", "1.2.3;touch bad", "01.2.3", "1.2.3\n4.5.6"):
            self.assertNotEqual(self.publish(version=version).returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
