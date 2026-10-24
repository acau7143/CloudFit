"""scripts/lib.sh 의 cron 블록 등록 테스트 (가짜 crontab 명령 사용, 실제 crontab 은 건드리지 않는다).

이미 수동으로 cron 을 등록한 운영 VM 에서 --apply 하면 같은 작업이 두 번 돌기 때문에,
cloudfit 블록 밖에 같은 스크립트를 실행하는 줄이 있으면 등록을 거부하는지 확인한다.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

OLD_LINE = "*/5 * * * * cd ~/CloudFit && python3 collectors/azure_exporter.py >> logs/azure_resource.log 2>&1"
START = "# >>> cloudfit:collector-azure >>>"


def _bash_ok():
    try:
        r = subprocess.run(
            ["bash", "-c", "command -v awk sed grep mktemp crontab >/dev/null 2>&1; command -v awk sed grep mktemp >/dev/null && echo ok"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return False
    return r.stdout.strip() == "ok"


pytestmark = pytest.mark.skipif(not _bash_ok(), reason="bash, awk, sed, grep 이 필요합니다")


@pytest.fixture
def env(tmp_path):
    """가짜 crontab(파일 하나에 저장)과 임시 HOME 을 만든다."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    stub = fakebin / "crontab"
    stub.write_text(
        '#!/usr/bin/env bash\n'
        'STORE="${FAKE_CRONTAB_FILE:?}"\n'
        'if [ "$1" = "-l" ]; then [ -f "$STORE" ] && cat "$STORE" || { echo "no crontab" >&2; exit 1; }\n'
        'elif [ "$1" = "-" ]; then cat > "$STORE"\n'
        'else cp "$1" "$STORE"; fi\n',
        encoding="utf-8", newline="\n",
    )
    stub.chmod(0o755)
    store = tmp_path / "crontab.txt"
    home = tmp_path / "home"
    home.mkdir()
    e = dict(os.environ)
    e["PATH"] = str(fakebin) + os.pathsep + e["PATH"]
    e["FAKE_CRONTAB_FILE"] = store.as_posix()
    e["HOME"] = home.as_posix()
    e.pop("CLOUDFIT_ALLOW_DUPLICATE_CRON", None)
    return {"env": e, "store": store, "home": home}


def run_install(env, apply, extra_env=None):
    script = (
        'cd "$CF_ROOT" && source scripts/lib.sh && r="$(mktemp)" && '
        'render_cron scripts/cron/collector-azure.cron /home/azureuser/CloudFit > "$r" && '
        'install_cron_block collector-azure "$r" "$CF_APPLY"'
    )
    e = dict(env["env"], CF_ROOT=ROOT.as_posix(), CF_APPLY="1" if apply else "0")
    e.update(extra_env or {})
    return subprocess.run(["bash", "-c", script], env=e, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def crontab_text(env):
    return env["store"].read_text(encoding="utf-8") if env["store"].exists() else ""


def test_preview_warns_about_existing_duplicate_line_and_changes_nothing(env):
    env["store"].write_text(OLD_LINE + "\n", encoding="utf-8")
    r = run_install(env, apply=False)
    assert r.returncode == 0
    assert "같은 스크립트를 실행하는 기존 줄" in r.stderr and "azure_exporter.py" in r.stderr
    assert crontab_text(env) == OLD_LINE + "\n"


def test_apply_is_refused_when_a_duplicate_exists(env):
    env["store"].write_text(OLD_LINE + "\n", encoding="utf-8")
    r = run_install(env, apply=True)
    assert r.returncode != 0
    assert "중복 등록을 막기 위해" in r.stderr
    assert crontab_text(env) == OLD_LINE + "\n"          # 아무것도 바뀌지 않았다
    assert not list(env["home"].glob("crontab.backup.*"))  # 등록하지 않았으니 백업도 없다


def test_apply_can_be_forced_with_env_var(env):
    env["store"].write_text(OLD_LINE + "\n", encoding="utf-8")
    r = run_install(env, apply=True, extra_env={"CLOUDFIT_ALLOW_DUPLICATE_CRON": "1"})
    assert r.returncode == 0
    text = crontab_text(env)
    assert OLD_LINE in text and START in text


def test_apply_without_duplicates_installs_block_and_keeps_other_lines(env):
    other = "0 4 * * * python3 /opt/other/job.py"
    env["store"].write_text(other + "\n", encoding="utf-8")
    r = run_install(env, apply=True)
    assert r.returncode == 0
    assert "기존 줄" not in r.stderr
    text = crontab_text(env)
    assert other in text and START in text and "azure_exporter.py" in text
    assert list(env["home"].glob("crontab.backup.*"))      # 기존 crontab 백업이 만들어졌다


def test_rerun_replaces_own_block_and_does_not_flag_it_as_duplicate(env):
    assert run_install(env, apply=True).returncode == 0
    r = run_install(env, apply=True)
    assert r.returncode == 0 and "기존 줄" not in r.stderr
    assert crontab_text(env).count(START) == 1


def test_comment_that_mentions_the_script_is_not_a_duplicate(env):
    env["store"].write_text("# collectors/azure_exporter.py 는 예전에 수동으로 돌렸다\n", encoding="utf-8")
    r = run_install(env, apply=True)
    assert r.returncode == 0 and "기존 줄" not in r.stderr


def test_other_cloud_script_is_not_a_duplicate(env):
    env["store"].write_text("*/5 * * * * cd ~/CloudFit && python3 collectors/gcp_exporter.py\n", encoding="utf-8")
    r = run_install(env, apply=True)
    assert r.returncode == 0 and "기존 줄" not in r.stderr
