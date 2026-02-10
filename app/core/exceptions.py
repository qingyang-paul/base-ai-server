"""数据库连接相关的异常类。"""


class DatabaseConnectionError(Exception):
    """数据库连接失败的基类异常。"""

    def __init__(self, service: str, detail: str):
        self.service = service
        self.detail = detail
        super().__init__(f"{service} connection error: {detail}")


class RedisConnectionError(DatabaseConnectionError):
    """Redis连接失败。"""

    def __init__(self, detail: str):
        super().__init__(service="Redis", detail=detail)


class PostgresConnectionError(DatabaseConnectionError):
    """Postgres连接失败。"""

    def __init__(self, detail: str):
        super().__init__(service="Postgres", detail=detail)


class ConnectionPoolExhaustedError(DatabaseConnectionError):
    """连接池耗尽。"""

    def __init__(self, service: str):
        super().__init__(service=service, detail="connection pool exhausted")
