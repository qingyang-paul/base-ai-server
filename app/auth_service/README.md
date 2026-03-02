# AuthService 说明书

## 1. 功能概述

AuthService 提供了完整的用户认证与授权解决方案，其核心模块与功能包括：

- **JWT 身份验证** (`core/config.py`, `core/security.py`)
  基于非对称加密 (RS256) 的 Token 签发与验证机制，支持短效 Access Token 和长效 Refresh Token 协同。
- **请求限流 Rate Limiting** (`core/limiter.py`)
  基于 Redis 和 FastAPI Limiter 构建限流体系，防范接口滥用。智能提取并构建限流键：优先使用用户 ID 限流，未登录时回退到使用客户端 IP 限流。
- **鉴权中间件** (`core/middleware.py`)
  提供 `AuthMiddleware` 拦截 HTTP 请求，自动解析 `Authorization: Bearer <token>` 头部，进行 Token 校验后将 `user_id` 注入到当前请求的上下文 (`request.state.user_id`) 中供全局使用。
- **客户端信息提取** (`core/dependencies.py`)
  提供 `get_client_info` 依赖，自动提取请求中的客户端 IP 地址 (`X-Forwarded-For` 或直连 IP) 和设备名 (通过 `User-Agent` 截取)，用于登录日志风控和追踪。
- **数据安全与加密** (`core/config.py`)
  配置了多轮哈希轮数以及使用 Fernet 算法进行敏感字段加密的内置设定。

---

## 2. 如何配置

服务核心配置位于 `app/auth_service/core/config.py`，配置参数通过系统的 `.env` 环境变量文件进行加载管理：

| 环境变量配置项 | 说明 | 默认值 / 备注 |
| :--- | :--- | :--- |
| `JWT_PRIVATE_KEY` | 用于**签名** JWT 的非对称私钥 | **必需配置** |
| `JWT_PUBLIC_KEY` | 用于**验证** JWT 的非对称公钥 | **必需配置** |
| `JWT_ALGORITHM` | JWT 签名算法 | `RS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access Token 过期时间 | `30` (分钟) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh Token 过期时间 | `7` (天) |
| `SECURITY_PASSWORD_HASH_ROUNDS` | 密码哈希加密轮数 | `12` |
| `SECURITY_ENCRYPTION_KEY` | 用于基础敏感数据对称加密的密钥 | 需提供 32 位 URL 安全的 Base64 编码 |

> **注意**: 在实例化具体组件或者服务类时，避免为核心配置设置默认值，需显式传入以确保配置缺失时能够第一时间报错。

---

## 3. 提供的 API 接口

所有对外提供的接口路由均挂载在 API 前缀 `/api/v1/auth` 之下。具体的请求载荷与参数可在 Swagger UI (`/docs`) 中查看。

### 3.1 注册与邮箱验证

- **`POST /api/v1/auth/signup`**
  - **功能**: 发起注册。接收邮箱、密码和可选昵称。
  - **限流**: 5 次 / 60 秒。
- **`POST /api/v1/auth/verify-email`**
  - **功能**: 校验邮箱收到的验证码。成功则完成注册并返回双 Token，同时在后台异步触发 `init_user_subscription_task` 初始化用户订阅与额度。
  - **限流**: 5 次 / 60 秒。

### 3.2 登录与令牌刷新

- **`POST /api/v1/auth/login`**
  - **功能**: 根据邮箱及密码进行登录。内部会验证身份并保存对应客户端环境的IP及设备信息，成功返回 Access Token 与 Refresh Token。
  - **限流**: 5 次 / 60 秒。
- **`POST /api/v1/auth/refresh`**
  - **功能**: 使用未过期的 Refresh Token 换取全新的 Access Token，同时会自动**轮换刷新** (Rotate) 发放新的 Refresh Token，保障账户安全。
  - **限流**: 5 次 / 60 秒。

### 3.3 密码安全管理

- **`POST /api/v1/auth/forgot-password`**
  - **功能**: 发起忘记密码请求。系统将验证邮箱并发送用于重置的验证码（为防止试探，返回模糊的统一提示消息）。
  - **限流**: 3 次 / 60 秒。
- **`POST /api/v1/auth/verify-reset-code`**
  - **功能**: 校验收到的密码重置验证码，合法后返回重置令牌信物(`otp_token` 等)。
  - **限流**: 5 次 / 60 秒。
- **`POST /api/v1/auth/reset-password`**
  - **功能**: 提交重置令牌和新密码进行密码重置。
  - **限流**: 3 次 / 60 秒。
- **`POST /api/v1/auth/change-password`**
  - **功能**: 已登录用户主动修改密码。需要原密码与新密码。**安全特性**：一旦密码修改成功，将会主动作废当前用户所有的 Refresh Token 会话，强制全端重新登录。
  - **权限**: 需提供有效 Access Token 证明已登录 (`get_current_user_id` 依赖)。
