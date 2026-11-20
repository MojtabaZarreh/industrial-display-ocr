from pymongo import MongoClient
from config.settings import MONGODB_DATABASE, MONGODB_TIMEOUT_MS, MONGODB_URI


def create_mongo_client() -> MongoClient:
    return MongoClient(MONGODB_URI, serverSelectionTimeoutMS=MONGODB_TIMEOUT_MS)

def check_mongo_connection(client: MongoClient) -> None:
    client.admin.command("ping")

def get_database(client: MongoClient):
    return client[MONGODB_DATABASE]
