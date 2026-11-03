"""Isolate an unreadable legacy store without modifying its table or files."""
import logging
from weakref import WeakKeyDictionary

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

LEGACY_TABLE = "network_observations"
LEGACY_MESSAGE = ("Dữ liệu huấn luyện tập trung cũ đang tạm ngưng do lỗi lưu trữ. "
                  "Hãy dùng dataset FL phân tán; dữ liệu cũ được giữ nguyên để phục hồi.")
_unavailable = WeakKeyDictionary()
logger = logging.getLogger("uvicorn.error")


def unavailable_tables(bind):
    engine = getattr(bind, "engine", bind)
    return dict(_unavailable.get(engine, {}))


def inspect_legacy_store(engine):
    """Only error 1932 on this optional table permits a degraded startup."""
    _unavailable[engine] = {}
    if engine.dialect.name != "mysql":
        return {}
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1 FROM network_observations LIMIT 0")
    except OperationalError as error:
        code = error.orig.args[0]
        if code == 1146:  # A fresh database: create_all will create the table.
            return {}
        if code != 1932:
            raise
        _unavailable[engine] = {LEGACY_TABLE: 1932}
        logger.warning("Legacy dataset storage unavailable (MySQL 1932). "
                       "Keeping the original table untouched; distributed FL remains available.")
    return unavailable_tables(engine)


def observations_available(db):
    return LEGACY_TABLE not in unavailable_tables(db.get_bind())


def require_observations(db):
    if not observations_available(db):
        raise HTTPException(503, LEGACY_MESSAGE)
