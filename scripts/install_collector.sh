#!/usr/bin/env bash
# 수집기 VM 설치: 가상환경 + 패키지 + 사전 점검 + cron 등록 (decisions/0015 단계 2)
#
# 사용법:  bash scripts/install_collector.sh <aws|gcp|azure> [--apply] [--skip-install] [--force]
#   (기본)           가상환경/패키지 설치와 사전 점검까지 하고, 등록할 crontab 을 보여주기만 한다.
#   --apply          사전 점검이 통과하면 crontab 에 등록한다 (기존 crontab 은 백업).
#   --skip-install   가상환경/패키지 설치를 건너뛴다 (이미 설치했을 때).
#   --force          사전 점검에 실패해도 cron 을 등록한다 (권장하지 않음).
#
# 먼저 할 일: cp .env.example .env 후 해당 클라우드 섹션을 채우고, 메모리·디스크 에이전트를 설치한다
#            (runbook/new-environment-setup.md).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

CLOUD="${1:-}"
[ -n "$CLOUD" ] || die "클라우드를 지정하세요: aws | gcp | azure"
shift || true
case "$CLOUD" in aws|gcp|azure) ;; *) die "알 수 없는 클라우드: $CLOUD (aws | gcp | azure)";; esac

APPLY=0; SKIP_INSTALL=0; FORCE=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1;;
    --skip-install) SKIP_INSTALL=1;;
    --force) FORCE=1;;
    *) die "알 수 없는 옵션: $arg";;
  esac
done

cd "$ROOT"
[ -f .env ] || die ".env 가 없습니다. 먼저: cp .env.example .env  (그리고 $CLOUD 섹션 채우기)"

if [ "$SKIP_INSTALL" != "1" ]; then
  make_venv "$ROOT" "$(find_python)" "$ROOT/requirements/$CLOUD.txt"
fi
mkdir -p logs

# CLOUDFIT_PYTHON 으로 점검용 파이썬을 바꿀 수 있다 (테스트용). 기본은 만든 가상환경.
PYBIN="${CLOUDFIT_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PYBIN" ] || PYBIN="$(find_python)"

echo
log "사전 점검 ($CLOUD)"
CHECK_OK=1
"$PYBIN" "$ROOT/scripts/check_prereqs.py" "$CLOUD" || CHECK_OK=0

RENDERED="$(mktemp)"
render_cron "$ROOT/scripts/cron/collector-$CLOUD.cron" "$ROOT" > "$RENDERED"

if [ "$CHECK_OK" != "1" ] && [ "$APPLY" = "1" ] && [ "$FORCE" != "1" ]; then
  install_cron_block "collector-$CLOUD" "$RENDERED" 0
  rm -f "$RENDERED"
  die "사전 점검에 실패해서 cron 을 등록하지 않았습니다. [FAIL] 항목을 해결한 뒤 다시 실행하세요."
fi

install_cron_block "collector-$CLOUD" "$RENDERED" "$APPLY"
rm -f "$RENDERED"

if [ "$CHECK_OK" != "1" ]; then
  warn "사전 점검에 [FAIL] 이 있습니다. 해결 후 다시 실행하세요."
  exit 1
fi
log "완료. 5~10분 뒤 logs/ 아래 로그와 서버 GET /resources?cloud=<클라우드> 를 확인하세요."
