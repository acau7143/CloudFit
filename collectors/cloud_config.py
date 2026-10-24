"""
수집기 공통 설정 로더 (decisions/0015 단계 1).

- 계정/프로젝트/리전/인스턴스처럼 환경마다 달라지는 값은 코드에 두지 않고
  프로젝트 루트의 .env(또는 셸 환경변수)에서 읽는다. 키 목록은 .env.example 참고.
- 필수 값은 기본값 없이 읽는다. 빠져 있으면 어떤 키가 빠졌는지 한 번에 알려주고
  종료한다 (기본값이 있으면 새 환경에서 조용히 남의 리소스를 조회하다 실패한다).
- 값이 환경마다 다르지만 흔한 기본값이 있는 것(디스크 장치명 등)은 선택 값으로 두고
  기본값을 .env.example에 명시한다.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# python-dotenv가 없는 환경에서도 셸 환경변수만으로 동작하게 방어
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


class ConfigError(RuntimeError):
    """필수 설정이 빠졌을 때 발생한다. 메시지에 빠진 키 목록이 들어있다."""


def get_env(name: str, default=None):
    """환경변수를 읽는다. 없거나 빈 문자열이면 default."""
    value = os.getenv(name)
    return value if value not in (None, "") else default


def require_env(*names: str) -> dict:
    """필수 환경변수를 한꺼번에 읽는다. 하나라도 없으면 빠진 키 전부를 담아 ConfigError."""
    values = {name: get_env(name) for name in names}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        raise ConfigError(
            "필수 설정이 없습니다: " + ", ".join(missing)
            + f"\n  → {PROJECT_ROOT / '.env'} 에 추가하세요 (예시: .env.example)"
        )
    return values


def exit_on_config_error(func, *args, **kwargs):
    """func를 실행하고 ConfigError면 메시지만 출력하고 종료 코드 2로 끝낸다 (traceback 없이)."""
    try:
        return func(*args, **kwargs)
    except ConfigError as error:
        print(f"[설정 오류] {error}", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------

def aws_region() -> str:
    return require_env("AWS_REGION")["AWS_REGION"]


def aws_instance_id(cli_value=None) -> str:
    """수집 대상 EC2 인스턴스 ID. --instance-id 인자가 있으면 그것이 우선한다."""
    if cli_value:
        return cli_value
    return require_env("AWS_INSTANCE_ID")["AWS_INSTANCE_ID"]


def aws_disk_dimensions() -> list:
    """CloudWatch Agent(CWAgent)의 disk_used_percent Dimension.

    에이전트가 내보내는 값과 정확히 일치해야 조회된다. 기본값은 Amazon Linux/Nitro
    인스턴스의 루트 볼륨 기준이며, 다르면 .env에서 바꾼다.
    """
    return [
        {"Name": "path", "Value": "/"},
        {"Name": "device", "Value": get_env("AWS_DISK_DEVICE", "nvme0n1p1")},
        {"Name": "fstype", "Value": get_env("AWS_DISK_FSTYPE", "xfs")},
    ]


# ---------------------------------------------------------------------------
# GCP
# ---------------------------------------------------------------------------

def gcp_project_id() -> str:
    return require_env("GCP_PROJECT_ID")["GCP_PROJECT_ID"]


def gcp_zone() -> str:
    return require_env("GCP_ZONE")["GCP_ZONE"]


def gcp_region() -> str:
    """GCP_REGION이 있으면 그것을, 없으면 zone에서 파생한다 (asia-northeast3-a → asia-northeast3)."""
    explicit = get_env("GCP_REGION")
    if explicit:
        return explicit
    return gcp_zone().rsplit("-", 1)[0]


def gcp_instance_name() -> str:
    return require_env("GCP_INSTANCE_NAME")["GCP_INSTANCE_NAME"]


def gcp_billing_account_id() -> str:
    return require_env("GCP_BILLING_ACCOUNT_ID")["GCP_BILLING_ACCOUNT_ID"]


def gcp_disk_device() -> str:
    """Ops Agent의 disk/percent_used 지표에서 조회할 장치. 기본값은 일반적인 부팅 디스크."""
    return get_env("GCP_DISK_DEVICE", "/dev/sda1")
