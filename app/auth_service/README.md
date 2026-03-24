# AuthService Manual

## 1. Feature Overview

AuthService provides a complete user authentication and authorization solution. Its core modules and features include:

- **JWT Authentication** (`core/config.py`, `core/security.py`)
  Token issuance and verification mechanism based on asymmetric encryption (RS256), supporting the synergy of short-lived Access Tokens and long-lived Refresh Tokens.
- **Rate Limiting** (`core/limiter.py`)
  Builds a rate limiting system based on Redis and FastAPI Limiter to prevent API abuse. Intelligently extracts and constructs rate limit keys: prioritizes user ID for rate limiting, and falls back to client IP rate limiting when not logged in.
- **Authentication Middleware** (`core/middleware.py`)
  Provides `AuthMiddleware` to intercept HTTP requests, automatically parsing the `Authorization: Bearer <token>` header, and after Token verification, injects the `user_id` into the current request context (`request.state.user_id`) for global use.
- **Client Information Extraction** (`core/dependencies.py`)
  Provides the `get_client_info` dependency to automatically extract the client IP address (`X-Forwarded-For` or direct IP) and device name (intercepted via `User-Agent`) from the request, serving login log risk control and tracking.
- **Data Security and Encryption** (`core/config.py`)
  Configured with built-in settings for multiple hash rounds and asymmetric encryption of sensitive fields using the Fernet algorithm.

---

## 2. Configuration Guide

The service's core configuration is located in `app/auth_service/core/config.py`, and configuration parameters are loaded and managed through the system's `.env` environment variables file:

| Environment Variable | Description | Default Value / Notes |
| :--- | :--- | :--- |
| `JWT_PRIVATE_KEY` | Asymmetric private key used to **sign** JWT | **Required** |
| `JWT_PUBLIC_KEY` | Asymmetric public key used to **verify** JWT | **Required** |
| `JWT_ALGORITHM` | JWT signing algorithm | `RS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access Token expiration time | `30` (minutes) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh Token expiration time | `7` (days) |
| `SECURITY_PASSWORD_HASH_ROUNDS` | Password hashing encryption rounds | `12` |
| `SECURITY_ENCRYPTION_KEY` | Key for symmetric encryption of underlying sensitive data | Requires a 32-byte URL-safe Base64 encoded string |

> **Note**: When instantiating specific components or service classes, avoid setting default values for core configurations. They must be explicitly passed to ensure that an error is thrown immediately when configurations are missing.

---

## 3. Provided API Endpoints

All exposed API routes are mounted under the API prefix `/api/v1/auth`. Specific request payloads and parameters can be viewed in the Swagger UI (`/docs`).

### 3.1 Registration and Email Verification

- **`POST /api/v1/auth/signup`**
  - **Function**: Initiates registration. Receives email, password, and optional nickname.
  - **Rate Limit**: 5 times / 60 seconds.
- **`POST /api/v1/auth/verify-email`**
  - **Function**: Verifies the verification code received via email. Upon success, completes registration and returns double Tokens, simultaneously triggering the `init_user_subscription_task` asynchronous background task to initialize the user's subscription and quota.
  - **Rate Limit**: 5 times / 60 seconds.

### 3.2 Login and Token Refresh

- **`POST /api/v1/auth/login`**
  - **Function**: Logs in based on email and password. Internally verifies identity and saves the corresponding client environment IP and device information, returning Access Token and Refresh Token upon success.
  - **Rate Limit**: 5 times / 60 seconds.
- **`POST /api/v1/auth/refresh`**
  - **Function**: Uses an unexpired Refresh Token to exchange for a new Access Token. It will also automatically **rotate and refresh** the issuance of a new Refresh Token to protect account security.
  - **Rate Limit**: 5 times / 60 seconds.

### 3.3 Password Security Management

- **`POST /api/v1/auth/forgot-password`**
  - **Function**: Initiates a forgot password request. The system will verify the email and send a verification code for resetting (to prevent probing, a blurred unified prompt message is returned).
  - **Rate Limit**: 3 times / 60 seconds.
- **`POST /api/v1/auth/verify-reset-code`**
  - **Function**: Verifies the received password reset code, returning a reset token credential (`otp_token`, etc.) after validation.
  - **Rate Limit**: 5 times / 60 seconds.
- **`POST /api/v1/auth/reset-password`**
  - **Function**: Submits the reset token and new password for password reset.
  - **Rate Limit**: 3 times / 60 seconds.
- **`POST /api/v1/auth/change-password`**
  - **Function**: Active password modification by logged-in users. Requires the original password and a new password. **Security Feature**: Once the password is changed successfully, it will actively invalidate all current Refresh Token sessions for the user, forcing re-login across all clients.
  - **Permission**: Requires a valid Access Token to prove logged-in status (`get_current_user_id` dependency).
