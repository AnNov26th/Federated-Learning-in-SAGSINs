import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from pathlib import Path
import json
from sqlalchemy.engine import make_url, URL

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/SAGSINs_db")
_managed_path=Path(__file__).resolve().parents[2]/".secrets"/"main-database.json"
if _managed_path.is_file():
    _configured=make_url(DATABASE_URL)
    _managed=json.loads(_managed_path.read_text(encoding="utf-8"))
    if (_configured.get_backend_name()=="mysql" and _configured.database==_managed["database"]
        and (_configured.port or 3306)==_managed["port"]
        and ((_configured.host or "localhost")==_managed["host"] or {_configured.host,_managed["host"]}<={"localhost","127.0.0.1"})):
        DATABASE_URL=URL.create("mysql+pymysql",username=_managed["user"],password=_managed["password"],
            host=_managed["host"],port=_managed["port"],database=_managed["database"])

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
