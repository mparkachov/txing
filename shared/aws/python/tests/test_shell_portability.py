import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]

DISALLOWED = [
    ("Bash shebang", re.compile(r"^#!.*\bbash\b")),
    ("Bash just shell", re.compile(r'set shell := \["bash"')),
    ("pipefail", re.compile(r"\bpipefail\b")),
    ("source command", re.compile(r"^\s*source\s+")),
    ("local command", re.compile(r"^\s*local(\s|$)")),
    ("double-bracket test", re.compile(r"\[\[|\]\]")),
    ("Bash regex test", re.compile(r"=~")),
    ("here string", re.compile(r"<<<")),
    ("process substitution", re.compile(r"<\s*<\(")),
    ("array assignment", re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=\(")),
    ("array append", re.compile(r"\+=\(")),
    ("array expansion", re.compile(r"\$\{[^}]+(\[@]|\[\*])")),
    ("arithmetic for loop", re.compile(r"\bfor\s*\(\(")),
    ("printf %q", re.compile(r"printf\s+['\"]%q")),
    ("mapfile/readarray", re.compile(r"\b(mapfile|readarray)\b")),
    ("BASH_SOURCE", re.compile(r"\bBASH_SOURCE\b")),
]


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines()]


def is_shell_surface(path: Path) -> bool:
    if "modules" in path.relative_to(REPO_ROOT).parts:
        return False
    if path.name == "justfile" or path.suffix in {".sh", ".bash", ".zsh"}:
        return True
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, UnicodeDecodeError):
        return False
    return bool(re.match(r"^#!.*\b(sh|bash|zsh)\b", first_line))


class ShellPortabilityTest(unittest.TestCase):
    def test_all_justfiles_export_repository_tmpdir(self) -> None:
        failures: list[str] = []
        for path in tracked_files():
            if path.name != "justfile" or not path.exists():
                continue
            if "modules" in path.relative_to(REPO_ROOT).parts:
                continue
            text = path.read_text(encoding="utf-8")
            if 'tmp_dir := project_root + "/tmp"' not in text and 'tmp_dir := root_dir + "/tmp"' not in text:
                failures.append(f"{path.relative_to(REPO_ROOT)}: missing repository tmp_dir")
            if "export TMPDIR := tmp_dir" not in text:
                failures.append(f"{path.relative_to(REPO_ROOT)}: missing TMPDIR export")
        self.assertEqual([], failures)

    def test_shell_scripts_and_justfiles_are_posix_sh_compatible(self) -> None:
        failures: list[str] = []
        for path in tracked_files():
            if not path.exists() or not is_shell_surface(path):
                continue
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for label, pattern in DISALLOWED:
                    if pattern.search(line):
                        relative = path.relative_to(REPO_ROOT)
                        failures.append(f"{relative}:{line_number}: {label}: {line.strip()}")
        self.assertEqual([], failures)

    def test_aws_deploy_helper_runs_under_posix_sh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_aws = temp_path / "aws"
            fake_aws.write_text(
                textwrap.dedent(
                    """\
                    #!/bin/sh
                    case "$1 $2" in
                      'sts get-caller-identity')
                        case "$*" in
                          *'--query Account'*) printf '123456789012\\n' ;;
                          *'--query Arn'*) printf 'arn:aws:iam::123456789012:user/test\\n' ;;
                          *) printf '{"Account":"123456789012","Arn":"arn:aws:iam::123456789012:user/test"}\\n' ;;
                        esac
                        ;;
                      's3api head-bucket'|'s3api head-object')
                        exit 0
                        ;;
                      'cloudformation package')
                        input=''
                        output=''
                        while [ "$#" -gt 0 ]; do
                          case "$1" in
                            --template-file) shift; input="$1" ;;
                            --output-template-file) shift; output="$1" ;;
                          esac
                          shift || true
                        done
                        cp "$input" "$output"
                        ;;
                      'cloudformation deploy')
                        printf 'deploy-ok\\n'
                        ;;
                      *)
                        printf 'unexpected aws call: %s\\n' "$*" >&2
                        exit 2
                        ;;
                    esac
                    """
                ),
                encoding="utf-8",
            )
            fake_aws.chmod(0o755)
            template = temp_path / "template.yaml"
            template.write_text(
                "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{temp_path}:{env.get('PATH', '')}",
                    "TMPDIR": str(temp_path / "project-tmp"),
                    "TXING_AWS_REGION": "eu-central-1",
                    "TXING_AWS_STACK": "town",
                }
            )
            result = subprocess.run(
                [
                    "sh",
                    "-c",
                    ". shared/aws/scripts/aws_lib.sh; deploy_template town \"$1\"",
                    "sh",
                    str(template),
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertIn("deploy-ok", result.stdout)
