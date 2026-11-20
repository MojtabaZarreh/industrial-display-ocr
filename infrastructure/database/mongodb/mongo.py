from pymongo.database import Database
from infrastructure.database.mongodb.client import check_mongo_connection, create_mongo_client, get_database

class MongoDB:
    def __init__(self) -> None:
        self._client = None
        self._database: Database | None = None

    def connect(self) -> None:
        if self._client is not None:
            return

        client = create_mongo_client()

        try:
            check_mongo_connection(client)
            database = get_database(client)
        except Exception:
            client.close()
            raise

        self._client = client
        self._database = database

    @property
    def database(self) -> Database:
        if self._database is None:
            raise RuntimeError(
                "MongoDB is not connected. Call connect() first."
            )

        return self._database

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

        self._client = None
        self._database = None
