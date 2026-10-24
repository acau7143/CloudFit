#!/usr/bin/env bash
# 서버 VM 설치: Docker Compose(DB + API + Grafana) + ML 배치 환경 + cron (decisions/0015 단계 2)
#
# 사용법:  bash scripts/install_server.sh [--apply] [--skip-docker] [--skip-install] [--no-grafana-provision]
#   (기본)           컨테이너 기동, 가상환경/패키지 설치, 사전 점검까지 하고 등록할 crontab 을 보여주기만 한다.
#   --apply          사전 점검이 통과하면 ML 배치 cron 을 등록한다 (기존 crontab 은 백업).
#   --skip-docker    컨테이너 기동을 건너뛴다 (이미 떠 있을 때).
#   --skip-install   가상환경/패키지 설치를 건너뛴다.
#   --no-grafana-provision   Grafana 데이터소스·대시보드 자동 설정(docker-compose.grafana.yml)을 쓰지 않는다.
#                    이미 수동으로 Grafana 를 설정해 둔 서버에서 쓴다.
#
# 먼저 할 일: cp .env.example .env 후 [서버/DB] 섹션을 채운다 (runbook/new-environment-setup.md).
# 이 VM에서 클라우드 수집도 한다면 끝난 뒤 install_collector.sh <클라우드> 를 따로 실행한다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

APPLY=0; SKIP_DOCKER=0; SKIP_INSTALL=0; GRAFANA_PROVISION=1
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1;;
    --skip-docker) SKIP_DOCKER=1;;
    --skip-install) SKIP_INSTALL=1;;
    --no-grafana-provision) GRAFANA_PROVISION=0;;
    *) die "알 수 없는 옵션: $arg";;
  esac
done

cd "$ROOT"
[ -f .env ] || die ".env 가 없습니다. 먼저: cp .env.example .env  ([서버/DB] 섹션 채우기)"

# .env 에서 값이 비어 있는 필수 키를 한꺼번에 알려준다 (값은 출력하지 않는다)
MISSING=""
for key in DB_PASSWORD DATABASE_URL; do
  if ! grep -Eq "^${key}=.+" .env; then MISSING="$MISSING $key"; fi
done
[ -z "$MISSING" ] || die ".env 에 빠진 키:$MISSING"

if [ "$SKIP_DOCKER" != "1" ]; then
  command -v docker >/dev/null 2>&1 || die "docker 가 없습니다. 설치 후 다시 실행하세요."
  if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
  else die "docker compose 플러그인도 docker-compose 도 없습니다."; fi
  docker info >/dev/null 2>&1 || die "docker 데몬에 접근할 수 없습니다 (실행 중인지, 현재 사용자가 docker 그룹인지 확인)."

  COMPOSE_FILES="-f docker-compose.yml"
  [ "$GRAFANA_PROVISION" = "1" ] && COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.grafana.yml"

  log "컨테이너 기동: $COMPOSE $COMPOSE_FILES up -d --build"
  # shellcheck disable=SC2086
  $COMPOSE $COMPOSE_FILES up -d --build

  log "서버 health 대기 (최대 60초)"
  ok=0
  for _ in $(seq 1 30); do
    if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then ok=1; break; fi
    sleep 2
  done
  [ "$ok" = "1" ] || die "서버가 응답하지 않습니다. 확인: $COMPOSE logs server"
  log "서버 정상: http://localhost:8000/health"

  if [ "$GRAFANA_PROVISION" = "1" ]; then
    gok=0
    for _ in $(seq 1 30); do
      if curl -fsS http://localhost:3000/api/health >/dev/null 2>&1; then gok=1; break; fi
      sleep 2
    done
    if [ "$gok" = "1" ]; then log "Grafana 정상: http://localhost:3000 (데이터소스·대시보드 자동 설정됨, 폴더 CloudFit)"
    else warn "Grafana 가 60초 안에 응답하지 않았습니다. 확인: $COMPOSE $COMPOSE_FILES logs grafana"; fi
  fi
fi

if [ "$SKIP_INSTALL" != "1" ]; then
  make_venv "$ROOT" "$(find_python)" "$ROOT/requirements.txt"
fi
mkdir -p logs

PYBIN="${CLOUDFIT_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PYBIN" ] || PYBIN="$(find_python)"

echo
log "사전 점검 (server)"
CHECK_OK=1
"$PYBIN" "$ROOT/scripts/check_prereqs.py" server || CHECK_OK=0

RENDERED="$(mktemp)"
render_cron "$ROOT/scripts/cron/server-ml.cron" "$ROOT" > "$RENDERED"

if [ "$CHECK_OK" != "1" ] && [ "$APPLY" = "1" ]; then
  install_cron_block "server-ml" "$RENDERED" 0
  rm -f "$RENDERED"
  die "사전 점검에 실패해서 cron 을 등록하지 않았습니다. [FAIL] 항목을 해결한 뒤 다시 실행하세요."
fi

install_cron_block "server-ml" "$RENDERED" "$APPLY"
rm -f "$RENDERED"

warn "방화벽: 수집기 VM 이 이 서버로 보내려면 포트 8000 을 열어야 합니다 (보안그룹/방화벽에서 수집기 IP 만 허용 권장)."
if [ "$GRAFANA_PROVISION" = "1" ]; then
  warn "Grafana: 관리자 비밀번호는 .env 의 GRAFANA_ADMIN_PASSWORD 입니다 (처음 기동할 때만 적용. 비어 있으면 admin). 3000 포트는 본인 IP 에만 여세요."
else
  warn "알려진 사항: --no-grafana-provision 이라 Grafana 는 수동 설정이며 비밀번호는 'admin' 고정입니다 (decisions/0015 단계 3)."
fi
[ "$CHECK_OK" = "1" ] || exit 1
log "완료."
