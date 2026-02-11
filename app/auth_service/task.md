# AuthService

2026.2.10

## Level 1

/auth_service/core/config.py

1. 定义用户密码加密的配置（secrete_key...）

2. 定义jwt的配置（secret_key, algorithm, access_token_expire_minutes, refresh_token_expire_minutes）

```
# 建议的配置结构
class Settings(BaseSettings):
    # JWT
    # 1. 私钥 (Private Key)：仅 Auth 服务持有，用于【签发】Token
    # 通常把 PEM 格式的内容读进来
    JWT_PRIVATE_KEY: str 
    # 2. 公钥 (Public Key)：所有业务服务持有，用于【验证】Token
    JWT_PUBLIC_KEY: str 
    # 3. 算法：固定为 RS256
    JWT_ALGORITHM: str = "RS256"
    # 4. access token 过期时间
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # 5. refresh token 过期时间
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 密码哈希
    # 配置算法参数 (如 rounds, memory_cost 等)，或者直接使用库的默认安全值
    SECURITY_PASSWORD_HASH_ROUNDS

    # 专门用于加密敏感数据 (TOTP Secret) 的密钥
    # 必须是 32 url-safe base64-encoded bytes
    # 生成命令: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SECURITY_ENCRYPTION_KEY: str


```

/auth_service/core/model.py

1. 定义jwt的payload

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import UUID
import time

# 1. 定义基础 Payload，包含所有 Token 共有的字段
class BaseTokenPayload(BaseModel):
    sub: str          # User ID
    exp: int          # 过期时间
    iat: int = Field(default_factory=lambda: int(time.time())) # 自动生成
    iss: str = "auth_service"
    jti: str          # 唯一ID
    
    # 业务通用字段
    token_version: int # 用于 invalidate all tokens for a user
    role: str

# 2. Access Token
class AccessTokenPayload(BaseTokenPayload):
    # 强制标记类型，防止混用
    type: Literal["access"] = "access"

# 3. Refresh Token
class RefreshTokenPayload(BaseTokenPayload):
    type: Literal["refresh"] = "refresh"
    
    # 必须字段：用于 Token Rotation
    family_id: str 

# 4. Magic Link / OTP Token
class MagicLinkPayload(BaseTokenPayload):
    # 允许多种类型，或者细分为不同 class
    type: Literal["magic_link", "password_reset", "verify_email"]
    
    email: str  # 这里必须有 email，因为用户可能还未登录/未注册
```

/auth_service/core/security.py

1. jwt的加密、解密、校验操作
2. 用户密码的加密和校验
3. 敏感数据加解密（如TOTP Secret，Fernet 引擎）

## Level 2

/auth_service/core/middleware.py
**中间件**

AuthMiddleware (自定义):

1. 检查Header。
2. Valid Token? -> request.state.user_id = "123"
3. Invalid/No Token? -> request.state.user_id = None

/app/main.py

1. 注册中间件

/auth_service/core/limiter.py
**限流器**

1. 使用fastapi_limiter实现限流
2. 尝试从state 缓存读user_id，没有的话从header尝试读
3. 定义identifier, 优先做用户级限流；如果没有user_id，回退到IP限流（区分内网IP，读取X-Forwarded-For）

/app/core/lifespan.py

1. 管理限流器的生命周期

/app/dependencies.py
**拿user_id**

1. 从request的state中获取user_id
2. 如果没有user_id，抛出异常

## Level 3

### **Redis存储格式**

| **业务对象** | **数据结构** | **Key 格式**                     | **Value 示例** | **TTL (过期)** | **用途**        |
| ------------ | ------------ | -------------------------------- | -------------- | -------------- | --------------- |
| 刷新令牌家族     | **String**   | `auth:rt_family:{family_id}` | `{current_jti, version}`        | 7天             | 核心： 配合 RTR 机制防重放   |
| 验证码       | **String**   | `auth:otp:{purpose}:{email}` | `{code, retry_count}`          | 300s (5min)    | 验证码校验 + 频次限制 |
| 限流计数器     | **String**   | `rate_limit:{route}:{ip_or_user}` | `count`          | 60s           | 接口限流 |

### **PG 存储内容**

#### user-auth-info

1. PG表(字段举例)

```python 

lass UserModel(Base):
    __tablename__ = "users_auth_info"

    # --- 基础信息 ---
    id: str = Column(String, primary_key=True) # UUID
    email: str = Column(String, unique=True, index=True)
    hashed_password: str = Column(String)
    
    # --- 核心安全 ---
    refresh_token_version: int = Column(Integer, default=1)
    totp_secret: Optional[str] = Column(String) # Encrypted
    mfa_enabled: bool = Column(Boolean, default=False)
    
    # --- 状态与资料 ---
    is_verified: bool = Column(Boolean, default=False)
    is_active: bool = Column(Boolean, default=True) # 封号开关
    nick_name: Optional[str]
    avatar_url: Optional[str]
    role: str = Column(String, default="user")

    # --- 🔴 建议新增字段 (Missing Fields) ---
    
    # 1. 记录何时改过密码
    # 用途：如果 Token 的签发时间早于这个时间，说明是改密码前的旧 Token，必须拒绝。
    password_changed_at: Optional[datetime] 
    

    # --- 审计 ---
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime
```

1. Python Service内部流转，不能返回前端

```python
class UserInternalSchema:
    # 在service和repo间流转，用于业务验证，不能返回给前端
    user_id: 
    email: 
    hashed_password: 
    refresh_token_version: 
    is_verified: 
    is_active:
    created_at: 
    avatar_url:
    nick_name:
    role: # Enum[user, admin...]
    updated_at: datetime
    last_login_at: datetime
    totp_secret：
    mfa_enabled： 

class UserUpdateSchema:
    user_id: Optional[]
    email: Optionalp[]
    hashed_password: Optional[]
    refresh_token_version: Optional[]
    is_verified: Optional[bool]
    is_active: 
    created_at: Optional[]
    avatar_url: Optional[]
    nick_name: Optional[]
    role: # Enum[user, admin...]
    updated_at: optional[datetime]
    last_login_at: optional[datetime]
    totp_secret：optional[]
    mfa_enabled： optional[]
```

#### refresh-token

1. PG表(字段举例)

```python
class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    # 使用 jti (JWT ID) 作为主键，因为它在 Token 里是唯一的
    jti: str = Column(String, primary_key=True)
    
    user_id: str = Column(ForeignKey("users.id"), index=True)
    
    # 核心字段：Token Rotation
    family_id: str = Column(String, index=True) # 标记一串相关的 Token
    parent_jti: Optional[str] = Column(String)  # 上一个 Token 是谁
    
    token_version: int 
    
    # 状态管理
    revoked_at: Optional[datetime]
    replaced_at: Optional[datetime] # 即使被替换了，也不要物理删除，保留记录用于审计
    expires_at: datetime
    
    # 审计
    created_at: datetime
    ip_address: str
    device_name: str
```

## Level 4

**注册流程-未登录**
/app/api/v1/auth/endpoints/signup.py

**路由1**
**申请账户**
@挂载限流器
Request:{email, password, nickname}
内部算法: auth_service.handle_signup()
Response: {msg: "success"}

/auth_service/core/exceptions.py

1. 重复注册
2. 发送邮件OTP过于频繁

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_signup**

1. check cool down: 检查是否已经存在合法otp，创建时间是否短于1分钟，如果短语一分钟，返回过于频繁错误
2. 检查email是否已存在（如果存在且is_verified=true，报错；如果存在但is_verified=false，视作覆盖注册）。
3. hash密码，存入PG
4. 生成6位otp，存redis
5. 后台异步发邮件

/app/taskiq.py
1. 全局注册Broker

/app/main.py
1. 注册taskiq

/auth_service/tasks/send_email.py
1. taskiq 异步发送邮件 (任务要接受otel 的trace id,保证日志、遥测、链路追踪一致性)

/auth_service/auth_repo.py

1. 检查email是否存在：读PG
2. hash密码：存PG
3. 6位otp：存redis

**路由2**
**验证邮箱**
@挂载限流器
Request:{email, code}
内部算法:auth_service.handle_verify_email()
Response: {access_token, refresh_token}

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_verify_email**

1. 校验code是否存在，验证合法后，删除code
2. 更新PG：is_verified=True
3. 更新成功后再发token

/auth_service/auth_repo.py

1. 6位otp+email：从redis读取
2. is_verified=True：更新PG

/auth_service/core/exceptions.py

1. 验证码无效（过期或者不正确）

## Levle 5

**登录流程-未登录**
/app/api/v1/auth/endpoints/login.py

**路由1**
**申请登录**
@挂载限流器
Request:{email, password}
内部算法: auth_service.handle_login()
Response: {access_token, refresh_token}

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_login**

1. 校验password
2. 更新PG：last_login_at
3. 生成access_token和refresh_token(保持token_version不变，新换一个family_id)
4. 存储refresh_token：PG

/auth_service/auth_repo.py

1. 通过email读PG
2. 校验is_verified=True # 验证过邮箱
3. 校验is_activate=True # 没被封号
4. 校验password
5. 更新last_login_at: PG
6. 存储refresh_token：PG
【读写原子性】

/auth_service/core/exceptions.py

1. 用户不存在
2. 密码错误
3. 邮箱未验证
4. 账户已封锁



## Level 6

**忘记密码-未登录**
/app/api/v1/auth/endpoints/forgot_password.py

**路由1**
**申请重置密码**
@挂载限流器
Request:{email}
内部算法: auth_service.handle_forgot_password()
Response: {msg: "success"} / {msg: "If an account exists for {email}, you will receive a verification code shortly."} # 避免枚举

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_forgot_password**

1. 校验email格式
2. 校验email是否存在
3. 生成6位otp，存redis
4. 发邮件

/auth_service/auth_repo.py

1. 校验email是否存在：读PG
2. 6位otp：存redis

**路由2**
**重置密码**
挂载限流器
Request:{email, code}
内部算法: auth_service.handle_verify_reset_code()
Response: {otp_token: jwt-otp-token(magiclinktoken)}

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_verify_reset_code**

1. 校验code是否存在，对比email匹配
2. 生成otp_token (magic link token)

/auth_service/auth_repo.py

1. 6位otp+email：从redis读取, 如果成功要销毁otp_code

/auth_service/core/exceptions.py

1. code不正确
2. 邮箱不匹配

**路由3**
**重置密码**
挂载限流器
Request:{reset_token, new_password}
内部算法: auth_service.handle_reset_password()
Response: {msg: "success"}

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_reset_password**

1. 计算token签名(无状态检验)
2. hash password
3. 更新PG：hashed_password
4. 下线已有的refresh_token(UserAuthInfo表的token_version += 1)
【3，4保证原子性】

/auth_service/auth_repo.py

1. 更新PG：hashed_password, updated_at

/auth_service/core/exceptions.py

1. reset_token无效(不存在&过期...)

## Level 7

**刷新token-已登录**
/app/api/v1/auth/endpoints/refresh_token.py

**路由1**
**刷新token**
@挂载限流器

Request:{refresh_token}  # 默认发送请求的是mobile，不是web
内部算法: auth_service.handle_refresh_token()
Response: {access_token, refresh_token}

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_refresh_token**
【拿锁-避免并发refresh请求刷出不同的token】
1. 校验refresh_token
2. 生成access_token和refresh_token(保持token_version不变，family_id不变)
3. 旧的refresh_token标记为replaced, 标记repalced_at, 重放时通过时间间隔，判断是并发还是攻击 -> 返回已经生成的child token，不要重新生成 【2，3原子】
4. 存储refresh_token：PG
【释放锁】

5. 返回token，放在HTTP body里，这里默认调用方是mobile不是web。

/auth_service/auth_repo.py

1. 校验refresh_token：读PG
3. 存储refresh_token：PG

/auth_service/core/exceptions.py

1. refresh_token无效（不存在&过期...）

## Level 8

**主动修改密码-已登录**
/app/api/v1/auth/endpoints/change_password.py

**路由1**
**修改密码**
@挂载限流器
@用get_user_id DI，拿到user_id

Request:{old_password, new_password}
内部算法: auth_service.handle_change_password()
Response: {msg: "success"}

/auth_service/auth_service.py【AuthService不直接操作数据库，都是用过AuthRepo来实现】
**handle_change_password**

1. 校验old_password
2. hash new_password
3. 更新PG：hashed_password & updated_at
4. 下线已有的refresh_token(UserAuthInfo表的token_version += 1)

/auth_service/auth_repo.py

1. 校验old_password：读PG
2. 更新PG：hashed_password, updated_at
3. 下线已有的refresh_token(UserAuthInfo表的token_version += 1)

/auth_service/core/exceptions.py

1. old_password不正确
