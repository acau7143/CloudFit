"""ml/anomaly_detector.py 의 모델 파일 처리 테스트.

새 환경에서는 ml/train.py 가 처음 돌기 전까지 model.pkl 이 없다. 이때 오류로 끝나지 않고
안내만 남기고 건너뛰어야 한다 (cron 이 10분마다 실행하므로 매번 traceback 이 쌓이면 안 된다).
"""
import asyncio
import os
import pickle
import sys

import pytest

pytest.importorskip("pandas")   # ml 패키지가 없는 최소 환경(수집기 VM 등)에서는 건너뛴다
pytest.importorskip("asyncpg")

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")  # 모듈 import 시 필요

from ml import anomaly_detector as ad


def test_load_returns_none_and_explains_when_model_file_is_missing(tmp_path, capsys):
    missing = tmp_path / "model.pkl"
    assert ad.load_saved_models(str(missing)) is None
    out = capsys.readouterr().out
    assert "학습된 모델 파일이 아직 없습니다" in out and "ml/train.py" in out


def test_load_reads_existing_model_file(tmp_path):
    path = tmp_path / "model.pkl"
    path.write_bytes(pickle.dumps({"AWS": {"model": "m", "scaler": "s"}}))
    assert ad.load_saved_models(str(path)) == {"AWS": {"model": "m", "scaler": "s"}}


def test_detect_and_save_skips_without_touching_the_database_when_model_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ad, "MODEL_PATH", str(tmp_path / "no-such-model.pkl"))

    async def must_not_connect(*args, **kwargs):
        raise AssertionError("모델이 없을 때는 DB 에 접속하면 안 된다")

    monkeypatch.setattr(ad.asyncpg, "connect", must_not_connect)
    asyncio.run(ad.detect_and_save())            # 예외 없이 끝나야 한다
    assert "이번 실행은 건너뜁니다" in capsys.readouterr().out
