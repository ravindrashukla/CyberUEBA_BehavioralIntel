"""Shared database connection helper for all pipeline modules."""

import os
import socket
import psycopg2

DEFAULT_PORT = "5437"

_port_reachable = None


def _check_port(host, port):
    """Fast TCP check — returns True if port is listening."""
    global _port_reachable
    if _port_reachable is not None:
        return _port_reachable
    try:
        s = socket.create_connection((host, int(port)), timeout=1)
        s.close()
        _port_reachable = True
    except (OSError, ConnectionRefusedError):
        _port_reachable = False
    return _port_reachable


def get_connection(autocommit: bool = False):
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("DB_PORT", DEFAULT_PORT)
    if not _check_port(host, port):
        raise ConnectionError(f"DB port {host}:{port} not reachable")
    db_url = os.getenv("DATABASE_URL_HOST")
    if db_url:
        conn = psycopg2.connect(db_url, connect_timeout=2)
    else:
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            dbname=os.getenv("DB_NAME", "cyber_ueba"),
            user=os.getenv("DB_USER", "cyber_ueba"),
            password=os.getenv("DB_PASSWORD", "password"),
            connect_timeout=2,
        )
    conn.autocommit = autocommit
    return conn
