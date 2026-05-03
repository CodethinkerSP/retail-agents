import os
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

KEY_VAULT_NAME = "murugesan-keyv"
DATABASE_URL_SECRET_NAME = "databaseurl"

if not KEY_VAULT_NAME:
    raise RuntimeError("AZURE_KEY_VAULT_NAME is required")

vault_url = f"https://{KEY_VAULT_NAME}.vault.azure.net"
credential = DefaultAzureCredential()
secret_client = SecretClient(vault_url=vault_url, credential=credential)

database_url = secret_client.get_secret(DATABASE_URL_SECRET_NAME).value

engine = create_async_engine(database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

