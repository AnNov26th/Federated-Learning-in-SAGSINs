"""MySQL only. Separate schemas/users for coordinator and each client."""
import json
import os
from pathlib import Path
import re
import secrets
import hashlib
import pymysql
from .storage import read_json, write_json

from .paths import ROOT, SECRETS


def credentials():
    path = SECRETS
    if not path.is_file():
        raise RuntimeError("Chưa khởi tạo FL phân tán. Chạy python -m sagsin.database rồi khởi động lại backend.")
    return read_json(path)


def connect(settings):
    return pymysql.connect(host=settings["host"], port=int(settings["port"]),
        user=settings["user"], password=settings["password"], database=settings["database"],
        charset="utf8mb4", connect_timeout=5, read_timeout=30, write_timeout=30,
        cursorclass=pymysql.cursors.DictCursor)


def provision(client_ids=None):
    from dotenv import load_dotenv
    from .topology import NODES
    load_dotenv(ROOT / ".env")
    from sqlalchemy.engine import make_url
    main_url = make_url(os.environ.get("DATABASE_URL", "mysql+pymysql://root:@127.0.0.1:3306/SAGSINs_db"))
    mysql_url = main_url if main_url.get_backend_name() == "mysql" else None
    host = os.environ.get("MYSQL_HOST", (mysql_url.host if mysql_url else None) or "127.0.0.1")
    port = int(os.environ.get("MYSQL_PORT", (mysql_url.port if mysql_url else None) or 3306))
    prefix = os.environ.get("SAGSIN_MYSQL_PREFIX", "sagsin_a_fl")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,15}", prefix):
        raise ValueError("SAGSIN_MYSQL_PREFIX must be 3–16 lowercase ASCII letters/digits/underscores")
    if prefix == "sagsin_fl_v2" or (mysql_url and prefix == mysql_url.database):
        raise ValueError("Use a dedicated prefix, separate from legacy and Second databases")
    secret_path = SECRETS
    existing = read_json(secret_path) if secret_path.exists() else None
    if existing and (existing["server"]["database"] != prefix or existing["server"]["host"] != host or int(existing["server"]["port"]) != port):
        raise ValueError("Existing credentials belong to another MySQL configuration; use a separate project/config")
    base = {"host": host, "port": port}
    values = existing or {"server": dict(base, database=prefix, user=prefix + "_server", password=secrets.token_urlsafe(24)),
        "clients": {node.id: dict(base, database=prefix + "_" + node.id.lower(),
            user=prefix + "_" + node.id.lower(), password=secrets.token_urlsafe(24)) for node in NODES}}
    for identifier in client_ids or []:
        if identifier not in values["clients"]:
            suffix = hashlib.sha256(identifier.encode()).hexdigest()[:12]
            values["clients"][identifier] = dict(base,database=prefix+"_c"+suffix,
                user=prefix+"_c"+suffix,password=secrets.token_urlsafe(24))
    admin = pymysql.connect(host=host, port=port,
        user=os.environ.get("MYSQL_ADMIN_USER", (mysql_url.username if mysql_url else None) or "root"),
        password=os.environ.get("MYSQL_ADMIN_PASSWORD", (mysql_url.password if mysql_url else None) or ""),
        charset="utf8mb4", connect_timeout=5)
    # Save secrets before grants so an interrupted provisioning can safely resume.
    write_json(secret_path, values)
    with admin:
        with admin.cursor() as cursor:
            for settings in [values["server"], *values["clients"].values()]:
                name, user = settings["database"], settings["user"]
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                cursor.execute("CREATE USER IF NOT EXISTS %s@'localhost' IDENTIFIED BY %s", (user, settings["password"]))
                # Only dedicated accounts from this project's prefix; never touch root or the old database.
                cursor.execute(f"GRANT SELECT, INSERT, UPDATE, CREATE, INDEX ON `{name}`.* TO %s@'localhost'", (user,))
        admin.commit()
    with connect(values["server"]) as db:
        with db.cursor() as cursor:
            cursor.execute("CREATE TABLE IF NOT EXISTS experiments (id CHAR(32) PRIMARY KEY, status VARCHAR(24) NOT NULL, created_at VARCHAR(40) NOT NULL, metadata_json LONGTEXT NOT NULL)")
        db.commit()
    for settings in values["clients"].values():
        with connect(settings) as db:
            with db.cursor() as cursor:
                cursor.execute("CREATE TABLE IF NOT EXISTS observations (id BIGINT AUTO_INCREMENT PRIMARY KEY, run_id CHAR(32) NOT NULL, split VARCHAR(16) NOT NULL, payload LONGTEXT NOT NULL, INDEX run_split (run_id, split))")
                cursor.execute("CREATE TABLE IF NOT EXISTS datasets (run_id CHAR(32) PRIMARY KEY, fingerprint CHAR(64) NOT NULL, config_json LONGTEXT NOT NULL)")
            db.commit()
    print(f"MySQL ready: {prefix} + {len(values['clients'])} isolated client schemas. Existing data preserved.")


def main():
    provision()
    provision_main_account()


def provision_main_account():
    """Give A's ORM its own account with no grants on client databases."""
    from dotenv import load_dotenv
    from sqlalchemy.engine import make_url
    load_dotenv(ROOT/".env")
    url=make_url(os.environ.get("DATABASE_URL","mysql+pymysql://root:@localhost:3306/SAGSINs_db"))
    if url.get_backend_name()!="mysql":return
    path=ROOT/".secrets"/"main-database.json"
    value=read_json(path) if path.exists() else dict(host=url.host or "127.0.0.1",port=url.port or 3306,
        database=url.database,user="sagsin_a_app",password=secrets.token_urlsafe(24))
    if value["database"]!=url.database:raise ValueError("Managed app account belongs to another main database")
    if not re.fullmatch(r"[A-Za-z0-9_]+",value["database"]):raise ValueError("Invalid main database name")
    with pymysql.connect(host=value["host"],port=value["port"],user=os.environ.get("MYSQL_ADMIN_USER",url.username or "root"),
        password=os.environ.get("MYSQL_ADMIN_PASSWORD",url.password or "")) as db:
        with db.cursor() as cur:
            cur.execute("CREATE USER IF NOT EXISTS %s@'localhost' IDENTIFIED BY %s",(value["user"],value["password"]))
            name=value["database"].replace("_",r"\_")
            cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES ON `{name}`.* TO %s@'localhost'",(value["user"],))
        db.commit()
    write_json(path,value)
    print("Main app account ready; grants limited to its original database. Restart backend to use it.")


if __name__ == "__main__":
    main()
