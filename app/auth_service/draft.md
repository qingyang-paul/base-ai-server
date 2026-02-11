# AuthService 模块

2026.02.10



## 路由层依赖注入局部中间件

数据流向：先通过限流器，解析`user_id`和`ip`，缓存`user_id` 。接着通过`get_user_id`，检查是否登录。


### fastapi-limiter

####  Identifier 

我们需要识别器：

1. 优先提取 `user_id`
2. 如果没有`user_id`，那就回退到ip限制


### get_current_user_id

放在dependencies.py，针对所有需要登录态的Server api，负责通过依赖注入的方式，从Header读取access token并转换为user_id，保存在request.state，方便后续业务接口的进一步处理。



## signup:

未登录态

+ **API:**`POST /auth/signup`
+ **Request:**`{ email, password, nickname }`
+ **Logic:**
  1. 校验 Email 格式、密码强度。
  2. 检查 Email 是否已存在（如果存在且 `is_verified=true`，报错；如果存在但 `is_verified=false`，视作覆盖注册）。
  3. Hash 密码，存入 PG (状态 `pending`)。
  4. 生成 6 位 OTP，存 Redis。
  5. 发邮件。
+ **Response:**`{"msg": "success" }`

**Step 2: 验证并自动登录**

+ **API:**`POST /auth/verify-email`
+ **Request:**`{ email, code }`
+ **Logic:**
  1. **限流检查：** (重要) 检查该 IP 或 Email 的试错频率。
  2. **验证：** 查 Redis，对比 `code`。如果不匹配 -> 报错。
  3. **激活：**
     * PG 更新: `UPDATE users SET is_verified = true WHERE email = ...`
     * **获取 User ID 和 Role** (用于生成 Token)。
  4. **清理：** 删除 Redis 里的 `signup_otp` Key。
  5. **发证 (关键)：**
     * 生成 `Access Token` (JWT)。
     * 生成 `Refresh Token` (存库或存 Redis)。

```python
class AuthSignupServerRequest(BaseModel):
    email:
    password: 
    nickname:

class AuthVerifyEmailServerRequest(BaseModel):
    email:
    code: 

```



## login:

Request: {Email, password} ->

auth_service.authticate_user_with_password() ->

auth_service.create_access_and_refresh_token() ->

return {access_token, refresh_token}



```python
class AuthLoginServerRequest(BaseModel):
    email:
    password:

```

## forget-password

+ **Step 1: 请求验证码**
+ **API:**`POST /auth/forgot-password`
+ **Request:**`{ email }`
+ **Logic:** 生成6位数字，存 Redis，发邮件。
+ **Response:**`{"msg": "success" }` (前端跳转到输入验证码界面)
+ **Step 2: 验证代码并重置**
+ 这里有两种做法，推荐 **做法 B**（更安全、更符合 RESTful）。
+ **用验证码换 Token：**
  - **API 1 (验证):**`POST /auth/verify-reset-code`
    * Request: `{ email, code }`
    * Response: `{ success: true, reset_token: "临时加密串" }`
    * _解释：_ 验证码输对了，后端给你一个有效期只有 5 分钟的 `reset_token`。
  - **API 2 (重置):**`POST /auth/reset-password`
    * Request: `{ reset_token, new_password }`
    * Response: `{"msg": "success" }`



```python
class AuthForgetPasswordServerRequest(BaseModel):
    email:

class AuthVerifyResetCodeServerReqeust(BaseModel):
    email:
    code:

class AuthResetPasswordServerRequest(BaseModel):
    reset_token:
    new_password:
```



## change-password

登录状态下，主动修改密码

+ **API:**`POST /auth/change-password`
+ **Header:**`Authorization: Bearer {access_token}` (**必须**需要登录态)

**Request:**

+ JSON

```plain
{
  "old_password": "my_current_password_123",
  "new_password": "my_new_secure_password_999"
}
```



1. **解析身份**：
   - 中间件 (Middleware) 验证 `Access Token` 是否有效。
   - 从 Token 中提取 `user_id`。
2. **验证旧密码 (关键防御)**：
   - 根据 `user_id` 从 Postgres 查出用户当前的 `password_hash`。
   - 使用哈希库 (如 bcrypt/argon2) 校验 `Request.old_password` 是否匹配数据库里的 Hash。
   - **如果匹配失败** -> 返回 `403 Forbidden` ("旧密码错误")。**绝不允许修改。**
3. **执行修改**：
   - 如果旧密码匹配 -> 将 `Request.new_password` 进行 Hash 加密。
   - 更新 Postgres：`UPDATE users SET password_hash = '...' WHERE id = ...`。
4. **安全善后 (强烈建议)**：
   - **场景**：假设用户的号被黑客在别的设备登录了。现在用户改了密码，黑客手里的 Token 应该立刻失效。
   - **操作**：
     * 如果你用了 Refresh Token 机制：在 Redis 中把该用户 ID 下 **所有** 的 Refresh Token 全部删除/加入黑名单。
     * 如果你只用了 Access Token：虽然不能立即让黑客掉线（除非做 Token 黑名单），但至少黑客过期后无法再续签。
   - **通知**：(可选) 给用户邮箱发一封信：“您的密码刚刚已修改，如果不是您本人操作，请立刻联系我们”。
5. **Response:**
   - {"msg": "success" }

```python
class AuthChangePasswordServerRequest(BaseModel):
    old_password:
    new_password:
```

## refresh

+ **Request:** 前端发现 Access Token 过期 -> 发送 `Refresh Token` 给后端。
+ **Verify:** 后端校验 `Refresh Token` (签名有效？没过期？数据库里存在且未被吊销？)。
+ **Rotate:**
+ 生成**新的**`Access Token`。
+ 检查`Refresh Token`的有效期，如果1小时以上，不管，如果少于1小时，将旧refresh tokenTTL设为60秒，签发新的rf 和 at。
+ **关键动作**：更换refresh token的时候，将旧token宽限一段TTL，防止并发。存储refresh token的表，要有一个字段，标记是否已经处于宽限期。
+ **Response:** 返回 `{ new_access_token, new_refresh_token }`。

```python
class AthRefreshServerReqeust(BaseModel):
    refresh_token:
    
```

## 总结 auth_service

### AuthService返回值和错误定义

```python
from typing import Generic, TypeVar, Optional
from dataclasses import dataclass
from enum import strEnum, auto

class AuthServiceErrorType(strEnum):
    """
    认证服务错误代码枚举
    继承 str 使得该 Enum 可以直接被 JSON 序列化
    """
    # Success
    NONE = None

    # --- 通用错误 ---
    INTERNAL_ERROR = auto()

    # --- 用户注册/账户相关 ---
    # 注册时，邮箱已被占用
    USER_EMAIL_EXISTS = auto()
    
    # 登录、改密、或 _get_user_with_cache 穿透数据库仍找不到用户
    USER_NOT_FOUND = auto()

    # --- 登录认证相关 ---
    # 登录时密码哈希比对失败
    INVALID_CREDENTIALS = auto()

    # 用户存在但未激活（未验证邮箱）
    USER_INACTIVE = auto()
    
    # 用户被封禁 (Banned)
    USER_BANNED = auto()

    # --- OTP (验证码) 相关 ---
    # 用户输入的 6 位验证码错误
    OTP_INVALID = auto()
    
    # Redis 中找不到该 Key（已过期），或者 TTL 耗尽
    OTP_EXPIRED = auto()

    # --- 频率限制/邮件服务 ---
    # 短时间内发送了太多次邮件，或者尝试了太多次错误验证码
    TOO_MANY_REQUESTS = auto()
    
    # 调用外部 SMTP 服务失败
    EMAIL_SEND_FAILED = auto()

    # --- JWT Token 校验 (格式/签名) ---
    # JWT 签名验证失败、格式错误、或者解码失败（用于 MagicLink 和 AccessToken）
    TOKEN_INVALID = auto()
    
    # JWT 的 exp 字段已过期
    TOKEN_EXPIRED = auto()

    # --- Token 安全/状态检查 ---
    # 检测到 user.token_version 与 Token 中的 version 不匹配（用户改密码了，或者被强制下线）
    TOKEN_REVOKED = auto()
    
    # Refresh Token 重用检测 (Case A)。
    # 场景：Token 已被标记为 replaced (旧的)，且超过宽限期。可能意味着黑客尝试使用旧 Token。
    TOKEN_REUSE_DETECTED = auto()

    # --- 密码管理 ---
    # 修改密码时，旧密码输入错误
    PASSWORD_MISMATCH = auto()
    
    # 新密码不符合复杂度要求
    PASSWORD_TOO_WEAK = auto()

# 定义一个泛型 T，代表“成功时携带的数据类型”
T = TypeVar("T")

@dataclass
class ServiceResult(Generic[T]):
    success: bool
    data: Optional[T] = None
    error_message: Optional[str] = None
    error_type: AuthServiceErrorType = AuthServiceErrorType.NONE 

    @classmethod
    def ok(cls, data: T = None):
        """快速创建一个成功的 Result"""
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, message: str, type: AuthServiceErrorType):
        """快速创建一个失败的 Result"""
        return cls(success=False, error_message=message, error_type=type)
    
    @property
    def is_failure(self):
        return not self.success
```

### AuthService核心定义

```python
class SignupServiceParams(BaseModel):
    """Signup request data"""
    email: EmailStr
    password: str
    full_name: Optional[str] = None



class LoginServiceParams(BaseModel):
    """Login request data"""
    email: EmailStr
    password: str

class ChangePasswordServiceParams(BaseModel):
    old_password: str 
    new_password: str

# 专门用于更新的 DTO (Data Transfer Object)
class UserUpdateServiceParams(BaseModel):
    # 所有字段都必须是 Optional，因为是“部分更新”
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    # 注意：不要包含 id, email 等不允许修改的字段



# 1. 登录/刷新成功的返回数据
class TokenWithUser(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    email: str

# 2. 验证结果 (比如校验 OTP 是否有效，或者校验 Email 是否存在)
class ValidationResult(BaseModel):
    is_valid: bool
    reason: Optional[str] = None # 如果无效，理由是什么

# 3. 注册后返回的简单数据 (比如只返回个 ID)
class UserRef(BaseModel):
    user_id: str
    email: EmailStr

# refresh后返回的数据
class AccessTokenPair(BaseModel):  
    access_token: str
    refresh_token: Optional[str] = None

class GeneralInfo:
    user_id: str
    message: str

class VerificationCode(BaseModel):
    """ 用于展示给用户的短码 """
    code: str   # 必填，6 digits
    ttl_seconds: int

class MagicLinkToken(BaseModel):
    """ 用于构造链接的长 Token """
    token: str  # 必填，JWT
    expires_at: datetime





class AuthService:
    def __init__(user_repo):
        self.repo = user_repo
        

    def _create_new_user_auth_info_waiting_for_eamil_verification(SignupServiceParams) ->ServiceResult[GeneralInfo]: 
        """ assemble User Data template with SignupData and default value for other property """ 

    def _create_verification_code_for_email_verification(email, user_id)  -> ServiceResult[VerificationCode]:
        """ create otp """

    def _temporarily_cache_verification_code_with_TTL(code: VerificationCode) -> ServiceResult[GeneralInfo]:
        """ restore in redis with well-formatted key """

        
    def _send_email_with_verification_code(email)  -> ServiceResult[GeneralInfo]:
        """ send otp to email """

    def handle_signup(SignupParams) -> ServiceResult[GeneralInfo]:
        self._create_new_user_waiting_for_eamil_verification()
        self._create_verification_code_for_email_verification
        self._temporarily_cache_verification_code_with_TTL()
        self._send_email_with_verification_code()

    def _check_verification_code_is_valid(code: VerificationCode) -> ServiceResult[ValidationResult]:
        """ 在redis里检查OTP是否过期，是否存在 """

    def handle_verify_email(code: VerificationCode) -> ServiceResult[AccessPair]:
        """ check email code, verify email after signup """
    
    def _create_magic_link_token_with_TTL(user_id, email, otp_scope: OTPScope) 
        -> ServiceResult[MagicLinkToken]
        """ jwt with payload, marking who calls this token, what is this token used for """ 
    
    def _temporarily_cache_magic_link_token() -> ServiceResult[GeneralInfo]:
        """ cache jwt in redes """
    
    def _check_magic_link_token_is_valid() -> ServiceResult[ValidationResult]:
        """ check jwt-token is existing, valid """
    
    def _update_user_auth_info(user: User, update_data: UserUpdateServiceParams) -> 
            ServiceResult[GeneralInfo]:
        """ 先抓取已有的user, 进行部分覆盖更新 """

    def _get_user_auth_info_by_id(user_id) -> ServiceResult{UserProfile}:
        """ call repo to get user """ 
        

    def handle_login(LoginServiceParams) -> Service[TokenWithUser]:
        """ check hashed-password valid """

    def handle_forget_password(email) -> ServiceResult[GeneralInfo]:
        """ check email existence and user validation, 
            generate and restore OTP,
            send Email with OTP
        """
    def handle_verify_reset_code(email, code) -> Result{MagicLinkToken}:
        """
            check code existence and user valid
        """

    def handle_reset_password(one_time_token, password) ->ServiceResult[GeneralInfo]:
        """ check token valid, update user password, offline refresh token """


    def _invalidate_refresh_token(user_id) -> ServiceResult[GeneralInfo]:
        """ 把现有的refresh token标记为失效(version)，强制用户下线 """

    def handle_change_password(ChangePasswordServiceParams) -> ServiceeResult[GeneralInfo]:
        """ check original password valid and update user, offline all refresh token """
    
    def _create_access_token() -> ServiceResult[AccessToken]:
        """ """
    def _create_refresh_token() -> ServiceResult[RefreshToken]:
        """  """
    def _replace_refresh_token() -> ServiceResult[GeneralInfo]:
        """  """

    def _check_access_token_is_valid_loose(access_token) 
            -> ServiceResult[ValidationResult]:
        """ only CPU calculation """

    def _check_access_token_is_valid_strict(access_token) 
            -> ServiceResult[ValidationResult]:
        """ check token_version, user validation ... """ 
        
    def _check_refresh_token_is_valid() 
            -> ServiceResult[ValidationResult]
        """ """ 

    def handle_refresh() -> ServiceResult[AccessTokenPair]:
        """ 
            # 1. 基础校验 (格式, 签名, 数据库是否存在)
   

    # 2. 检查用户状态 (有没有被封号, 全局版本号是否变了)


    # ====================================================
    # 3. 核心分支逻辑
    # ====================================================

    # Case A: 宽限期内 (并发请求)
    # 数据库里已经被标记了 replaced_at (说明它是旧的)，但还没过 30s
    
        else:
            # 超过宽限期：黑客攻击 / 严重延迟 -> 报警并踢下线
          

    # Case B: 需要轮换 (快过期了)
    # 比如: 剩余有效期 < 1 天
    
        # 1. 标记当前 RT 为“即将失效” (设置 replaced_at)
        
        
        # 2. 生成新 RT (使用同一个user.token_version)
        
        # 3. 生成新 AT
        
        return { "access_token": new_at, "refresh_token": new_rt }

    # Case C: 正常情况 (还没过期，且离过期还早)
    # 比如: 刚发出来 1 小时
        # 1. 只生成新 AT
        
        # 2. RT 不变 (或者返回旧的，看前端协议)
        return { "access_token": new_at }
        """
        
    

        
```

### jwt-token payload

```python
class OTPScope(strEnum):
  # OTP服务于什么业务
    VERIFY_EMAIL = auto()
    FORGET_PASSWORD = auto()
    ...
   
 class JWTType(strEnum):
  	ACCESS_TOKEN = auto()
    REFRESH_TOKEN = auto()
    OTP = auto()

class JWTPayload(BaseModel):
    # --- 标准字段 (Standard Claims) ---
    sub: str          # 对应 user_id
    exp: int          # 对应 expired_at (Unix Timestamp)
    iat: int          # [新增] 签发时间 (Unix Timestamp)
    iss: str = "auth" # [新增] 签发服务名
    jti: str          # 唯一 ID (用于防重放/黑名单)

    # --- 业务核心字段 (Business Claims) ---
    token_version: int  # 核心！用于全局撤回 (Global Logout)
    role: str           # 权限控制 (user/admin)

    # --- 用途绑定 (Purpose Binding) ---
    type: JWTType
    # 例如: "access", "magic_link_login", "password_reset"
    otp_scope: Optional[OTPScope]
    
    
    # ⚠️ 只有在 "Verify Email" 或 "Magic Link" 的 Token 里才放 email
    # Access Token 尽量别放
    email: Optional[str] = None
```

## 总结AuthRepo

### PG 存储的内容

user-auth-info - PG表

```python
user_id:
email: 
hashed_password:
refresh_token_version:
is_verified: bool
is_active: 
created_at: datetime
avatar_url:
nick_name:
role: # Enum[user, admin...]
updated_at: datetime
last_login_at: datetime
totp_secret：
mfa_enabled： 
```

user-auth-info - Python DTO

```python
class UserAuthInfoInstance:
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
    
    

class UserAuthInfoPiece:
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

refresh token

```python
user_id:
token_version:
is_evoked:
replaced_at:  # 当 token 发生轮换时，旧 token 不应该立即删除或标记为 revoked，而是标记 replaced_at = now()。
revoked_at: 
created_at:
family_id:
parent_id:
refresh_token:
expires_at: 
device_name: 
ip_address: 
```

### Redis存储的内容
| **业务对象** | **数据结构** | **Key 格式**                     | **Value 示例** | **TTL (过期)** | **用途**        |
| ------------ | ------------ | -------------------------------- | -------------- | -------------- | --------------- |
| Access token | String       | Auth:access_token:{access_token} | user_id        | 看配置         | 登录令牌        |
| 邮箱索引     | **String**   | `auth:idx:email:{email}`         | user_id        | 无             | 通过邮箱查 ID   |
| 验证码       | **String**   | `auth:otp:code:{purpose}:{code}` | email          | 300s (5min)    | 短信/邮件验证码 |
| 认证令牌     | **String**   | `auth:otp:token:{token_string}`  | email          | 300s           | 验证码          |


### AuthRepo返回值和错误定义

```python
from enum import StrEnum, auto

class AuthRepoErrorType(StrEnum):
    # 成功
    NONE = auto()
    
    # 常见业务相关错误
    NOT_FOUND = auto()              # 查无此人/记录
    DUPLICATE = auto()              # 唯一键冲突 (如 Email 已存在)
    CONSTRAINT_VIOLATION = auto()   # 违反约束 (如外键不存在，或数据不合法)
    STALE_OBJECT = auto()           # 乐观锁错误 (版本号不匹配，用于你的Token轮换)
    
    # 系统级错误
    TIMEOUT = auto()                # 数据库超时
    CONNECTION_ERROR = auto()       # 连不上数据库
    INTERNAL = auto()               # 其他未知的 SQL 报错


from typing import Generic, TypeVar, Optional, Any
from dataclasses import dataclass

# 定义泛型 T
T = TypeVar("T")

@dataclass
class RepoResult(Generic[T]):
    success: bool
    data: Optional[T] = None
    
    # 错误分类 (供 Service 做逻辑判断)
    error_type: AuthRepoErrorType = AuthRepoErrorType.NONE
    
    # 错误提示 (供开发者调试或日志记录)
    error_message: Optional[str] = None
    
    # 原始异常 (可选：如果你想在 Service 层记录完整的堆栈信息)
    exception: Optional[Exception] = None

    @property
    def is_failure(self):
        return not self.success

    @classmethod
    def ok(cls, data: T = None):
        """返回成功结果"""
        return cls(success=True, data=data, error_type=RepoErrorType.NONE)

    @classmethod
    def fail(cls, error_type: RepoErrorType, message: str = "", exception: Exception = None):
        """返回失败结果"""
        return cls(success=False, error_type=error_type, message=message, exception=exception)

```

### AuthRepo核心定义

```python
class AuthUserRepository:
    # (SQL / 持久层)
# 这部分主要处理 users 表和 refresh_tokens 表。

# A. 基础用户查询与创建
def create_user_auth_info(signup_data: SignupParams) -> User

# 用途：handle_signup。

# 逻辑：插入新用户，设置 is_verified=False。需处理 UniqueViolation（邮箱重复）。

def get_user_by_email(email: str) -> Optional[User]

# 用途：handle_login, handle_signup (检查存在性), handle_forget_password。

def get_user_by_id(user_id: str) -> Optional[User]

# 用途：_get_user_with_cache (缓存未命中时的回源查询)。

# B. 用户状态更新
def update_user_verification(user_id: str, is_verified: bool) -> bool

# 用途：handle_verify_email。

 def update_password(user_id: str, new_password_hash: str) -> bool

# 用途：handle_reset_password, handle_change_password。

# 副作用：通常这里也需要顺便调用 increment_token_version。

 def update_user_auth_info(user_id: str, data: UserUpdateParams) -> User

# 用途：_update_user_profile。

 def increment_user_token_version(user_id: str) -> int

# 用途：_invalidate_refresh_token (强制下线), handle_change_password。

# 逻辑：UPDATE users SET token_version = token_version + 1 WHERE id = ...。

# C. Refresh Token 核心逻辑 (支持 Token 轮换)
# 你的 handle_refresh 逻辑非常重，需要专门的表结构支持（或 JSONB）。假设你有一张 refresh_tokens 表。

def get_refresh_token_record(token_hash: str) -> Optional[RefreshTokenRecord]

# 用途：handle_refresh。

# 返回：需要返回 revoked, replaced_at, expires_at, user_id 等字段，用于判断 Case A/B/C。

def save_refresh_token(record: RefreshTokenRecord) -> None

# 用途：登录或刷新成功后，保存新的 RT 记录。

def rotate_refresh_token(old_token_hash: str, new_token_hash: str) -> None

# 用途：handle_refresh (Case B - 轮换)。

# 逻辑：事务操作 -> 1. 将旧 Token 的 replaced_at 设为当前时间。 2. 插入新 Token 记录。

def revoke_all_tokens_for_user(user_id: str) -> None

# 用途：handle_refresh (Case A - 检测到 Reuse 攻击时), handle_change_password。

# 逻辑：删除该用户所有 RT，或将它们全部标记为 revoked。

class AuthCacheRepository 
# (Redis / 缓存层)
# 这部分处理 TTL（过期时间）和高频读取。

# A. 验证码 (OTP)
def save_email_verification_code(email: str, code: str, ttl: int) -> None

# 用途：_temporarily_cache_verification_code_with_TTL。

def get_email_verification_code(email: str) -> Optional[str]

# 用途：_check_verification_code_is_valid。

def delete_email_verification_code(email: str) -> None

# 用途：验证成功后立即删除（防止二次使用）。

# B. Magic Link / Reset Token
def save_magic_link_token(token_jti: str, user_id: str, ttl: int) -> None

# 用途：_temporarily_cache_magic_link_token。

# 注意：这里通常存 jti (JWT ID) 到 Redis 白名单，或者反过来存黑名单。根据你的 _check 逻辑决定。

def exists_magic_link_token(token_jti: str) -> bool

# 用途：_check_magic_link_token_is_valid。

```

## 