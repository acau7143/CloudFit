#!/usr/bin/env bash
# install_collector.sh / install_server.sh 가 공통으로 쓰는 함수 (직접 실행하지 않는다)

log()  { printf '[설치] %s\n' "$*"; }
warn() { printf '[경고] %s\n' "$*" >&2; }
die()  { printf '[중단] %s\n' "$*" >&2; exit 1; }

# 3.10 이상 파이썬을 찾는다. 없으면 python3 를 쓰되 경고한다
# (Python 3.9 는 boto3 지원이 2026-04-29 에 끝났다. README 전제는 3.11+).
find_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return 0; fi
  done
  if command -v python3 >/dev/null 2>&1; then
    warn "Python 3.10 이상을 찾지 못해 $(python3 --version 2>&1) 를 사용합니다."
    warn "  Amazon Linux: sudo dnf install -y python3.11 / Ubuntu: sudo apt install -y python3.11 python3.11-venv"
    command -v python3
    return 0
  fi
  die "python3 가 없습니다."
}

# $1=저장소 루트, $2=파이썬 경로, $3=requirements 파일. 루트의 .venv 를 만들고 패키지를 설치한다.
make_venv() {
  local root="$1" py="$2" req="$3"
  [ -f "$req" ] || die "requirements 파일이 없습니다: $req"
  if [ ! -x "$root/.venv/bin/python" ]; then
    log "가상환경 생성: $root/.venv ($("$py" --version 2>&1))"
    "$py" -m venv "$root/.venv" \
      || die "가상환경 생성 실패. Ubuntu/Debian 이면: sudo apt install -y python3-venv"
  fi
  log "패키지 설치: $req"
  "$root/.venv/bin/python" -m pip install --quiet --upgrade pip
  "$root/.venv/bin/python" -m pip install --quiet -r "$req"
}

# $1=템플릿, $2=저장소 루트 → @ROOT@, @PYTHON@ 를 치환해 stdout 으로 출력
render_cron() {
  local tpl="$1" root="$2"
  [ -f "$tpl" ] || die "cron 템플릿이 없습니다: $tpl"
  sed -e "s|@ROOT@|$root|g" -e "s|@PYTHON@|$root/.venv/bin/python|g" "$tpl"
}

# $1=블록 이름, $2=렌더링된 cron 파일, $3=apply(1이면 실제 등록)
# crontab 에는 '# >>> cloudfit:이름 >>>' ~ '# <<< cloudfit:이름 <<<' 블록 하나로만 넣는다.
# 다시 실행하면 같은 이름의 블록만 교체하고, 그 밖의 줄(기존 운영 설정 포함)은 건드리지 않는다.
install_cron_block() {
  local name="$1" rendered="$2" apply="$3"
  local start="# >>> cloudfit:$name >>>" end="# <<< cloudfit:$name <<<"

  echo
  echo "---- crontab 블록: cloudfit:$name ----"
  cat "$rendered"
  echo "--------------------------------------"

  if [ "$apply" != "1" ]; then
    log "미리보기입니다. 실제로 등록하려면 --apply 를 붙여 다시 실행하세요."
    return 0
  fi

  command -v crontab >/dev/null 2>&1 || die "crontab 명령이 없습니다."
  local backup current next
  backup="$HOME/crontab.backup.$(date +%Y%m%d-%H%M%S)"
  current="$(mktemp)"; next="$(mktemp)"
  crontab -l > "$current" 2>/dev/null || : > "$current"
  cp "$current" "$backup"
  log "기존 crontab 백업: $backup"

  awk -v s="$start" -v e="$end" '$0==s{skip=1;next} $0==e{skip=0;next} !skip' "$current" > "$next"
  { cat "$next"; echo "$start"; cat "$rendered"; echo "$end"; } | crontab -
  rm -f "$current" "$next"
  log "crontab 등록 완료 (cloudfit:$name). 확인: crontab -l / 되돌리기: crontab $backup"
}
