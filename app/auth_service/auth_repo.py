from datetime import datetime
from typing import Optional

from redis.asyncio import Redis
from asyncpg import Connection
from loguru import logger

from app.auth_service.core.schema import UserInternalSchema, UserUpdateSchema

class AuthRepo:
    def __init__(self, connection: Connection, redis: Redis):
        self.connection = connection
        self.redis = redis

    async def get_user_by_email(self, email: str) -> Optional[UserInternalSchema]:
        query = "SELECT * FROM users_auth_info WHERE email = $1"
        row = await self.connection.fetchrow(query, email)
        if row:
            return UserInternalSchema(**dict(row))
        return None

    async def create_user(self, user_data: dict) -> UserInternalSchema:
        # Construct INSERT query
        columns = list(user_data.keys())
        values = list(user_data.values())
        placeholders = [f"${i+1}" for i in range(len(values))]
        
        query = f"""
            INSERT INTO users_auth_info ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            RETURNING *
        """
        logger.info(f"Creating user with email: {user_data.get('email')}")
        row = await self.connection.fetchrow(query, *values)
        return UserInternalSchema(**dict(row))
    
    async def update_user(self, user_id: str, updates: UserUpdateSchema):
        # Generate dynamic update query
        update_data = updates.model_dump(exclude_unset=True)
        if not update_data:
            return

        set_clauses = []
        values = []
        # user_id is $1
        values.append(user_id)
        
        for i, (key, value) in enumerate(update_data.items()):
            set_clauses.append(f"{key} = ${i+2}")
            values.append(value)
            
        # Add updated_at
        set_clauses.append("updated_at = NOW()")

        query = f"""
            UPDATE users_auth_info 
            SET {', '.join(set_clauses)}
            WHERE id = $1
        """
        await self.connection.execute(query, *values)
        logger.info(f"Updated user {user_id} with {list(update_data.keys())}")

    async def save_otp(self, email: str, code: str, purpose: str):
        key = f"auth:otp:{purpose}:{email}"
        # Expire in 5 minutes (300s)
        await self.redis.setex(key, 300, code)
        logger.debug(f"Saved OTP for {email} (purpose={purpose})")

    async def get_otp(self, email: str, purpose: str) -> Optional[str]:
        key = f"auth:otp:{purpose}:{email}"
        result = await self.redis.get(key)
        if isinstance(result, bytes):
            return result.decode("utf-8")
        return result
    
    async def delete_otp(self, email: str, purpose: str):
        key = f"auth:otp:{purpose}:{email}"
        await self.redis.delete(key)
        logger.debug(f"Deleted OTP for {email} (purpose={purpose})")
        
    async def get_otp_ttl(self, email: str, purpose: str) -> int:
        key = f"auth:otp:{purpose}:{email}"
        return await self.redis.ttl(key)

    async def create_refresh_token(self, token_data: dict):
        columns = list(token_data.keys())
        values = list(token_data.values())
        placeholders = [f"${i+1}" for i in range(len(values))]
        
        query = f"""
            INSERT INTO refresh_tokens ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
        """
        await self.connection.execute(query, *values)
        logger.debug(f"Created refresh token for user {token_data.get('user_id')}")
