
import os
from pathlib import Path
from urllib.parse import (
    quote_plus,
    urlsplit,
    urlunsplit,
    parse_qsl,
    urlencode,
)

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "dev-only-change-this-secret-key",
    )

    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

    if DATABASE_URL:
        parts = urlsplit(DATABASE_URL)

        # Always use the installed PyMySQL driver.
        if parts.scheme in ("mysql", "mysql+pymysql"):
            parts = parts._replace(scheme="mysql+pymysql")

        # Remove Aiven CLI-style SSL parameters from the URL.
        query = dict(parse_qsl(parts.query, keep_blank_values=True))

        for key in ("ssl-mode", "ssl_mode", "ssl-ca", "ssl_ca"):
            query.pop(key, None)

        query.setdefault("charset", "utf8mb4")

        SQLALCHEMY_DATABASE_URI = urlunsplit(
            parts._replace(query=urlencode(query))
        )

        # Configure SSL separately using the Aiven CA certificate.
        CA_CERT_PATH = os.getenv(
            "MYSQL_CA_CERT",
            str(BASE_DIR / "ca.pem"),
        )

        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {
                "ssl": {
                    "ca": CA_CERT_PATH,
                    "check_hostname": True,
                }
            }
        }

    else:
        db_user = quote_plus(
            os.getenv("DATABASE_USER", "hiresphere_app")
        )
        db_password = quote_plus(
            os.getenv("DATABASE_PASSWORD", "")
        )
        db_host = os.getenv("DATABASE_HOST", "127.0.0.1")
        db_port = os.getenv("DATABASE_PORT", "3306")
        db_name = os.getenv("DATABASE_NAME", "hiresphere_db")

        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{db_user}:{db_password}@"
            f"{db_host}:{db_port}/{db_name}?charset=utf8mb4"
        )

    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = int(
        os.getenv("MAX_CONTENT_LENGTH", "5242880")
    )

    UPLOAD_FOLDER = str(BASE_DIR / "private_uploads")

    MAIL_SERVER = os.getenv("MAIL_SERVER", "").strip()
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "").strip()
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1") == "1"
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "").strip()

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
