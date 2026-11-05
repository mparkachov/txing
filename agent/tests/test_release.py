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
import base64, hashlib, json, os, pathlib, shutil, sys, zipfile
root = pathlib.Path(os.environ["FIXTURE"])
args = sys.argv[1:]
def flag(name): return args[args.index(name)+1]
def emit(value): print(json.dumps(value))
def fail(message): print(message, file=sys.stderr); sys.exit(1)
mode = (root/"mode").read_text()
records_file = root/"versions.json"
records = json.loads(records_file.read_text()) if records_file.exists() else {}
latest = (root/"latest-version").read_text() if (root/"latest-version").exists() else "3.0"
def save_records(): records_file.write_text(json.dumps(records))
def image_version(version):
    if version not in records: fail("ResourceNotFoundException")
    request = dict(records[version])
    if version == latest:
        request.update(json.loads((root/"request.json").read_text()))
        if mode == "inactive-build": request["status"] = "INACTIVE"
        if mode == "wrong-artifact": request["codeArtifact"]["uri"] = "s3://other/other.zip"
        if mode == "normalized-base": request["baseImageVersion"] = "2.0"
        if mode == "wrong-base": request["baseImageVersion"] = "2.1"
    return request
tool = pathlib.Path(sys.argv[0]).name
with (root/"calls.jsonl").open("a") as f: f.write(json.dumps([tool]+args)+"\n")
if tool in ("just", "sleep"): sys.exit(0)
if tool == "gh":
    shutil.copyfile(root/"package.zip", pathlib.Path(flag("--dir"))/"txing-agent-release-linux-arm64.zip")
    with zipfile.ZipFile(root/"package.zip") as archive:
        (root/"download-version").write_text(json.loads(archive.read("release.json"))["version"])
    sys.exit(0)
service, operation = args[:2]
if service == "s3api":
    if operation == "get-bucket-versioning":
        emit({"Status":mode.title()} if mode in ("enabled","suspended") else {})
    elif operation == "list-objects-v2":
        items = [{"Key":str(p.relative_to(root/"s3")),"Size":p.stat().st_size}
                 for p in (root/"s3").rglob("*") if p.is_file() and str(p.relative_to(root/"s3")).startswith(flag("--prefix"))]
        emit({"Contents":items,"IsTruncated":mode=="incomplete-objects"})
    elif operation == "delete-objects":
        if mode == "s3-delete-denied": fail("AccessDenied")
        request = json.loads(pathlib.Path(flag("--delete")[7:]).read_text())
        deleted, errors = [], []
        for item in request["Objects"]:
            key = root/"s3"/item["Key"]
            if mode == "partial-s3-delete" and key.name == "controller.zip":
                errors.append({"Key":item["Key"],"Code":"AccessDenied"})
            else:
                key.unlink(missing_ok=True); deleted.append(item)
        if mode == "ambiguous-s3-delete": fail("RequestTimeout")
        emit({"Deleted":deleted,"Errors":errors})
    elif operation == "put-object":
        key = root/"s3"/flag("--key")
        assert flag("--if-none-match") == "*"
        if key.exists(): fail("PreconditionFailed")
        key.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(flag("--body"), key)
        emit({"ETag":hashlib.md5(key.read_bytes()).hexdigest()})
    elif operation == "get-object":
        key = root/"s3"/flag("--key")
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
    if operation == "list-managed-microvm-image-versions": emit({"items":[{"imageVersion":"2" if mode=="normalized-base" else "2.0","status":"EXPIRED" if mode=="expired-base" else "AVAILABLE"}]})
    elif operation == "list-microvm-image-versions":
        if mode == "inventory-denied": fail("AccessDenied")
        if mode == "missing-image" and not (root/"request.json").exists(): fail("ResourceNotFoundException")
        if mode == "retention-inventory-denied" and (root/"s3/agent"/(root/"download-version").read_text()/"built.json").exists(): fail("AccessDenied")
        items = [image_version(v) for v in records]
        if mode == "duplicate-builds" and items: items.append(dict(items[0], imageVersion="4.0"))
        result = {"items":items}
        if mode == "incomplete-versions": result["nextToken"] = "unread-page"
        emit(result)
    elif operation in ("create-microvm-image", "update-microvm-image"):
        if mode == "replay-rejected" and (root/"request.json").exists():
            fail("ValidationException: The provided clientToken was used with different request parameters.")
        request = json.loads(pathlib.Path(flag("--cli-input-json")[7:]).read_text())
        (root/"request.json").write_text(json.dumps(request))
        number = int((root/"next-version").read_text()) if (root/"next-version").exists() else 3
        version = str(number)+".0"
        records[version] = dict(request,imageArn=os.environ["IMAGE"],imageVersion=version,
            state="FAILED" if mode=="failed-build" else "SUCCESSFUL",status="ACTIVE",createdAt=1700000000+number*60)
        save_records()
        (root/"latest-version").write_text(version)
        (root/"next-version").write_text(str(number+1))
        emit({"imageArn":os.environ["IMAGE"],"imageVersion":version})
    elif operation == "delete-microvm-image-version":
        if mode == "image-delete-denied": fail("AccessDenied")
        version = flag("--image-version")
        records[version]["state"] = "DELETING" if mode in ("delete-timeout","delete-poll-denied","delete-not-found","async-delete") else "DELETED"
        save_records(); emit({"imageIdentifier":os.environ["IMAGE"],"imageVersion":version,"state":records[version]["state"]})
    elif operation == "get-microvm-image-version":
        if mode == "poll-unavailable": fail("RequestTimeout")
        version = flag("--image-version")
        if records.get(version,{}).get("state") == "DELETING":
            if mode == "delete-poll-denied": fail("AccessDenied")
            if mode == "delete-not-found":
                records[version]["state"] = "DELETED"; save_records(); fail("ResourceNotFoundException")
            if mode == "async-delete":
                pending = root/("pending-"+version)
                if pending.exists(): records[version]["state"] = "DELETED"; save_records()
                else: pending.touch()
        emit(image_version(version))
    elif operation == "get-microvm-image": emit({"imageArn":os.environ["IMAGE"],"state":"UPDATED"})
    else: fail("unexpected image operation")
elif service == "lambda" and operation == "get-function-configuration":
    if mode == "controller-mismatch": emit({"CodeSha256":"incorrect"}); sys.exit(0)
    state = json.loads((root/"stack.json").read_text())
    key = next(p["ParameterValue"] for p in state["Parameters"] if p["ParameterKey"]=="ControllerKey")
    value = (root/"s3"/key).read_bytes()
    emit({"CodeSha256":base64.b64encode(hashlib.sha256(value).digest()).decode()})
else: fail("unexpected AWS operation")
'''


class AgentReleaseTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
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
        for name in ("aws", "gh", "just", "sleep"):
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

    def package(self, label="one", version="1.2.3"):
        path = self.root / label / "package"
        result = subprocess.run([
            "cmake", f"-DSTAGE_DIR={self.stage}", f"-DSOURCE_DIR={self.source}",
            f"-DPACKAGE_DIR={path}", f"-DVERSION={version}", "-P", str(ROOT / "agent/cmake/Release.cmake"),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = path.parent / "txing-agent-release-linux-arm64.zip"
        shutil.copyfile(archive, self.root / "package.zip")
        return archive

    def publish(self, mode="success", version="1.2.3", base_version="2.0"):
        (self.root / "mode").write_text(mode)
        recipe = (ROOT / "agent/justfile").read_text().split("publish version:\n", 1)[1]
        recipe = textwrap.dedent(recipe.split("\n# Operator-run initial", 1)[0])
        recipe = recipe.replace("{{project_root}}", str(ROOT))
        script = self.root / "publish.sh"
        script.write_text(recipe)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "FIXTURE": str(self.root),
               "IMAGE": IMAGE, "TMPDIR": str(self.root), "TXING_AWS_STACK": "test",
               "TXING_AGENT_BASE_IMAGE_VERSION": base_version}
        return subprocess.run(["sh", str(script), version], env=env, text=True, capture_output=True)

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def parameters(self):
        return {p["ParameterKey"]: p["ParameterValue"] for p in json.loads((self.root / "stack.json").read_text())["Parameters"]}

    def fresh_publications(self):
        state = json.loads((self.root / "stack.json").read_text())
        for parameter in state["Parameters"]:
            if parameter["ParameterKey"] == "ImageName": parameter["ParameterValue"] = "disabled"
            if parameter["ParameterKey"] in ("ImageVersion", "Release"): parameter["ParameterValue"] = ""
            if parameter["ParameterKey"] in ("AutomationEnabled", "PrerequisitesConfirmed"): parameter["ParameterValue"] = "false"
        (self.root / "stack.json").write_text(json.dumps(state))
        (self.root / "next-version").write_text("1")

    def new_publication(self, version, mode="success"):
        self.package("release-" + version, version=version)
        return self.publish(mode, version=version)

    def prepare_retirement(self, mode):
        self.fresh_publications()
        for version in ("1.2.3", "1.2.4"):
            result = self.new_publication(version)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.new_publication("1.2.5", mode)

    def live_versions(self):
        return {v for v, record in json.loads((self.root / "versions.json").read_text()).items()
                if record["state"] != "DELETED"}

    def bundle_keys(self, version):
        return {str(p.relative_to(self.root / "s3")) for p in (self.root / "s3/agent" / version).rglob("*") if p.is_file()}

    def assert_retained(self, versions, releases):
        self.assertEqual(self.live_versions(), set(versions))
        expected = {"microvm.zip", "controller.zip", "provenance.zip", "hooks.json", "stack.yaml",
                    "release.json", "SHA256SUMS", "build-input.json", "built.json"}
        for release in releases:
            self.assertEqual(self.bundle_keys(release), {f"agent/{release}/{name}" for name in expected})

    def assert_no_retirement(self, calls):
        self.assertFalse(any(call[1:3] in (["lambda-microvms", "delete-microvm-image-version"],
                                         ["s3api", "delete-objects"]) for call in calls))

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
        for mode in ("failed-build", "inactive-build", "wrong-artifact", "wrong-base", "expired-base", "receipt-denied"):
            with self.subTest(mode=mode):
                # Each mode must reach its own validation, independent of a prior failed image.
                for name in ("request.json", "versions.json", "latest-version", "next-version"):
                    (self.root / name).unlink(missing_ok=True)
                shutil.rmtree(self.root / "s3", ignore_errors=True)
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

    def test_normalized_managed_base_preserves_request_and_reuses_receipt(self):
        for _ in range(2):
            result = self.publish("normalized-base", base_version="2")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.parameters()["Release"], "1.2.3")
        request = json.loads((self.root / "s3/agent/1.2.3/build-input.json").read_text())
        self.assertEqual(request["baseImageVersion"], "2")
        receipt = json.loads((self.root / "s3/agent/1.2.3/built.json").read_text())
        self.assertEqual(receipt["build"]["baseImageVersion"], "2.0")
        builds = [call for call in self.calls() if call[1:3] == ["lambda-microvms", "update-microvm-image"]]
        self.assertEqual(len(builds), 1)

    def test_interrupted_build_recovers_exact_version_without_resubmission(self):
        self.assertNotEqual(self.publish("poll-unavailable").returncode, 0)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        builds = [call for call in self.calls() if call[1:3] == ["lambda-microvms", "update-microvm-image"]]
        self.assertEqual(len(builds), 1)
        request = (self.root / "s3/agent/1.2.3/build-input.json").read_bytes()
        receipt = json.loads((self.root / "s3/agent/1.2.3/built.json").read_text())
        self.assertEqual(receipt["token"], hashlib.sha256(request).hexdigest())

    def test_recovery_avoids_rejected_update_replay(self):
        self.assertNotEqual(self.publish("poll-unavailable").returncode, 0)
        result = self.publish("replay-rejected")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.parameters()["ImageVersion"], "3.0")
        self.assertEqual(sum(call[1:3] == ["lambda-microvms", "update-microvm-image"] for call in self.calls()), 1)

    def test_ambiguous_matching_versions_stop_before_selection_or_submission(self):
        self.assertNotEqual(self.publish("poll-unavailable").returncode, 0)
        result = self.publish("duplicate-builds")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.parameters(), self.initial_parameters)
        self.assertEqual(sum(call[1:3] == ["lambda-microvms", "update-microvm-image"] for call in self.calls()), 1)

    def test_conflicting_build_configuration_is_not_adopted(self):
        self.assertNotEqual(self.publish("poll-unavailable").returncode, 0)
        path = self.root / "request.json"
        original = json.loads(path.read_text())
        for field, value in (("buildRoleArn", "another-role"), ("hooks", {}),
                             ("resources", [{"minimumMemoryInMiB":8192}]),
                             ("environmentVariables", {"UNREQUESTED":"value"}),
                             ("additionalOsCapabilities", ["ALL"])):
            with self.subTest(field=field):
                changed = dict(original)
                changed[field] = value
                path.write_text(json.dumps(changed))
                result = self.publish("replay-rejected")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.parameters(), self.initial_parameters)
        self.assertEqual(sum(call[1:3] == ["lambda-microvms", "update-microvm-image"] for call in self.calls()), 1)

    def test_unavailable_inventory_never_submits_a_build(self):
        for mode in ("inventory-denied", "missing-image"):
            with self.subTest(mode=mode):
                self.assertNotEqual(self.publish(mode).returncode, 0)
                self.assertEqual(self.parameters(), self.initial_parameters)
        self.assertFalse(any(call[1:3] == ["lambda-microvms", "update-microvm-image"] for call in self.calls()))

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
        result = self.publish("missing-image")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any(call[1:3] == ["lambda-microvms", "create-microvm-image"] for call in self.calls()))
        self.assertEqual(self.parameters()["AutomationEnabled"], "false")

    def test_invalid_version_stops_before_download(self):
        for version in ("latest", "1.2.3;touch bad", "01.2.3", "1.2.3\n4.5.6"):
            self.assertNotEqual(self.publish(version=version).returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_versioned_or_suspended_bucket_stops_before_upload(self):
        for mode in ("enabled", "suspended"):
            with self.subTest(mode=mode):
                result = self.publish(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("new unversioned artifact bucket", result.stderr)
                self.assertEqual(self.parameters(), self.initial_parameters)
        self.assertFalse(any(call[1:3] == ["s3api", "put-object"] for call in self.calls()))

    def test_three_successful_publications_keep_two_complete_bundles(self):
        self.fresh_publications()
        for count, release in enumerate(("1.2.3", "1.2.4", "1.2.5"), 1):
            result = self.new_publication(release)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            expected_versions = [f"{number}.0" for number in range(max(1, count - 1), count + 1)]
            expected_releases = [f"1.2.{number + 2}" for number in range(max(1, count - 1), count + 1)]
            self.assert_retained(expected_versions, expected_releases)
            self.assertEqual(sum(p.is_file() for p in (self.root / "s3").rglob("*")), min(count, 2) * 9)
        self.assertEqual(self.bundle_keys("1.2.3"), set())
        operations = self.calls()
        deletion = next(i for i, call in enumerate(operations) if call[1:3] == ["lambda-microvms", "delete-microvm-image-version"])
        confirmed = next(i for i, call in enumerate(operations) if i > deletion and call[1:3] == ["lambda-microvms", "get-microvm-image-version"] and call[call.index("--image-version")+1] == "1.0")
        objects = next(i for i, call in enumerate(operations) if call[1:3] == ["s3api", "delete-objects"])
        self.assertLess(deletion, confirmed)
        self.assertLess(confirmed, objects)

    def test_failed_build_preserves_two_good_releases_and_is_pruned_later(self):
        result = self.prepare_retirement("failed-build")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.parameters()["Release"], "1.2.4")
        self.assertTrue(self.bundle_keys("1.2.3"))
        self.assertTrue(self.bundle_keys("1.2.4"))
        self.assert_no_retirement(self.calls())
        result = self.new_publication("1.2.6")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_retained(["2.0", "4.0"], ["1.2.4", "1.2.6"])
        self.assertEqual(self.bundle_keys("1.2.3"), set())
        self.assertEqual(self.bundle_keys("1.2.5"), set())

    def test_failed_selection_preserves_old_images_and_bundles(self):
        result = self.prepare_retirement("selection-denied")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.parameters()["Release"], "1.2.4")
        self.assert_retained(["1.0", "2.0", "3.0"], ["1.2.3", "1.2.4", "1.2.5"])
        self.assert_no_retirement(self.calls())

    def test_controller_verification_failure_prevents_retirement(self):
        result = self.prepare_retirement("controller-mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assert_retained(["1.0", "2.0", "3.0"], ["1.2.3", "1.2.4", "1.2.5"])
        self.assert_no_retirement(self.calls())

    def test_image_deletion_failure_retains_sources_and_retry_does_not_build(self):
        result = self.prepare_retirement("image-delete-denied")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Release selected, but retention is incomplete", result.stderr)
        self.assertEqual(self.parameters()["ImageVersion"], "3.0")
        self.assertEqual(len(self.bundle_keys("1.2.3")), 9)
        self.assertFalse(any(call[1:3] == ["s3api", "delete-objects"] for call in self.calls()))
        result = self.publish(version="1.2.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_retained(["2.0", "3.0"], ["1.2.4", "1.2.5"])
        self.assertEqual(sum(call[1:3] in (["lambda-microvms", "create-microvm-image"], ["lambda-microvms", "update-microvm-image"]) for call in self.calls()), 3)

    def test_partial_s3_deletion_retries_orphan_objects_without_rebuilding(self):
        result = self.prepare_retirement("partial-s3-delete")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Release selected, but retention is incomplete", result.stderr)
        self.assertEqual(self.live_versions(), {"2.0", "3.0"})
        self.assertEqual(self.bundle_keys("1.2.3"), {"agent/1.2.3/controller.zip"})
        result = self.publish(version="1.2.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.bundle_keys("1.2.3"), set())
        self.assert_retained(["2.0", "3.0"], ["1.2.4", "1.2.5"])
        self.assertEqual(sum(call[1:3] == ["lambda-microvms", "update-microvm-image"] for call in self.calls()), 2)

    def test_ambiguous_s3_delete_response_can_retry_after_all_keys_are_gone(self):
        result = self.prepare_retirement("ambiguous-s3-delete")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.bundle_keys("1.2.3"), set())
        result = self.publish(version="1.2.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_retained(["2.0", "3.0"], ["1.2.4", "1.2.5"])

    def test_async_image_delete_is_confirmed_before_sources_are_removed(self):
        result = self.prepare_retirement("async-delete")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.bundle_keys("1.2.3"), set())
        self.assert_retained(["2.0", "3.0"], ["1.2.4", "1.2.5"])
        self.assertTrue(any(call[0] == "sleep" for call in self.calls()))

    def test_deleted_version_not_found_is_a_valid_deletion_confirmation(self):
        result = self.prepare_retirement("delete-not-found")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_retained(["2.0", "3.0"], ["1.2.4", "1.2.5"])

    def test_delete_poll_access_denied_preserves_all_source_objects(self):
        result = self.prepare_retirement("delete-poll-denied")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.bundle_keys("1.2.3")), 9)
        self.assertFalse(any(call[1:3] == ["s3api", "delete-objects"] for call in self.calls()))

    def test_image_deletion_wait_is_bounded_and_retains_sources(self):
        result = self.prepare_retirement("delete-timeout")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("five minutes", result.stderr)
        self.assertEqual(len(self.bundle_keys("1.2.3")), 9)
        self.assertFalse(any(call[1:3] == ["s3api", "delete-objects"] for call in self.calls()))

    def test_retention_inventory_failure_reports_selected_release(self):
        result = self.publish("retention-inventory-denied")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.parameters()["Release"], "1.2.3")
        self.assertIn("Release selected, but retention is incomplete", result.stderr)
        self.assert_no_retirement(self.calls())

    def test_incomplete_version_inventory_never_submits_a_build(self):
        result = self.publish("incomplete-versions")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[1:3] == ["lambda-microvms", "update-microvm-image"] for call in self.calls()))
        self.assert_no_retirement(self.calls())

    def test_incomplete_s3_inventory_prevents_any_retirement(self):
        result = self.prepare_retirement("incomplete-objects")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_retirement(self.calls())

    def test_creation_timestamps_with_different_offsets_order_builds_correctly(self):
        self.assertNotEqual(self.prepare_retirement("image-delete-denied").returncode, 0)
        records = json.loads((self.root / "versions.json").read_text())
        records["1.0"]["createdAt"] = "2026-11-05T19:00:00.000000+02:00"
        records["2.0"]["createdAt"] = "2026-11-05T18:15:00.000000+01:00"
        records["3.0"]["createdAt"] = "2026-11-05T17:30:00Z"
        (self.root / "versions.json").write_text(json.dumps(records))
        result = self.publish(version="1.2.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_retained(["2.0", "3.0"], ["1.2.4", "1.2.5"])

    def test_pending_or_foreign_version_stops_retention_before_deletion(self):
        self.assertNotEqual(self.prepare_retirement("image-delete-denied").returncode, 0)
        original = json.loads((self.root / "versions.json").read_text())
        for changed in (dict(original["1.0"], state="IN_PROGRESS"),
                        dict(original["1.0"], codeArtifact={"uri":"s3://foreign/agent/1.2.3/microvm.zip"})):
            records = dict(original)
            records["1.0"] = changed
            (self.root / "versions.json").write_text(json.dumps(records))
            before = len(self.calls())
            result = self.publish(version="1.2.5")
            self.assertNotEqual(result.returncode, 0)
            self.assert_no_retirement(self.calls()[before:])

    def test_selected_image_outside_retained_pair_is_never_deleted(self):
        self.assertNotEqual(self.prepare_retirement("image-delete-denied").returncode, 0)
        records = json.loads((self.root / "versions.json").read_text())
        records["3.0"]["createdAt"] = 0
        (self.root / "versions.json").write_text(json.dumps(records))
        before = len(self.calls())
        result = self.publish(version="1.2.5")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Selected image is outside", result.stderr)
        self.assert_no_retirement(self.calls()[before:])

    def test_unrelated_objects_are_preserved(self):
        for key in ("unrelated/readme", "agent/notes.txt", "agent/images/manual-source.zip"):
            path = self.root / "s3" / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unrelated")
        result = self.prepare_retirement("success")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for key in ("unrelated/readme", "agent/notes.txt", "agent/images/manual-source.zip"):
            self.assertEqual((self.root / "s3" / key).read_text(), "unrelated")

    def test_missing_retained_bundle_object_prevents_image_deletion(self):
        self.assertNotEqual(self.prepare_retirement("image-delete-denied").returncode, 0)
        (self.root / "s3/agent/1.2.4/provenance.zip").unlink()
        before = len(self.calls())
        result = self.publish(version="1.2.5")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_retirement(self.calls()[before:])
        self.assertEqual(len(self.bundle_keys("1.2.3")), 9)

    def test_large_object_retirement_uses_bounded_s3_batches(self):
        self.fresh_publications()
        for index in range(1001):
            path = self.root / "s3/agent/0.0.1" / f"artifact-{index}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("abandoned publication")
        result = self.new_publication("1.2.3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.bundle_keys("0.0.1"), set())
        batches = [call for call in self.calls() if call[1:3] == ["s3api", "delete-objects"]]
        self.assertEqual(len(batches), 2)
        for call in batches:
            request = json.loads(Path(call[call.index("--delete")+1][7:]).read_text())
            self.assertLessEqual(len(request["Objects"]), 1000)


if __name__ == "__main__":
    unittest.main()
