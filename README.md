# Base AI Server

Base AI Server is a fully-featured, highly modular general Artificial Intelligence backend server framework. The project provides high-performance asynchronous HTTP interfaces via FastAPI, and deeply integrates PostgreSQL, Redis, Taskiq asynchronous task queue, and a comprehensive OpenTelemetry observability trace.

## 1. Core Infrastructure

The system's underlying facilities are encapsulated in the `app/core/` directory, responsible for carrying global non-business foundational capabilities:

- **Global Configuration Loading (`app/core/config.py`)**: Uses Pydantic `BaseSettings` to centrally manage environment variables, including work environments, Redis/PG database connection strings, SMTP email, Telemetry configurations, etc., serving as the single global source of truth for configuration.
- **Observability and Distributed Tracing (`app/core/telemetry.py`)**: Integrates OpenTelemetry (OTel), configures the OTLP gRPC exporter, and automatically instruments every FastAPI HTTP request to generate Span and Trace IDs using `FastAPIInstrumentor`.
- **Structured Logging (`app/core/logger.py`)**: Deeply customized Loguru, allowing one-click switching to JSON format output based on the environment toggle. It also intercepts the logs of the standard library and Uvicorn, and automatically extracts the OpenTelemetry `trace_id` in the current context to write into every log entry through a Patcher, achieving a perfect "log-trace" binding.
- **Background Asynchronous Task Middleware (`app/core/taskiq_middleware.py`)**: Uses Taskiq to process time-consuming background tasks. Created custom `OpentelemetryMiddleware`, which can automatically serialize and inject the current Trace context when triggering asynchronous tasks, ensuring that background tasks dispatched across processes remain on the same trace pipeline as the main request.
- **Dependency Injection Hub (`app/dependencies.py`)**: The core dependency injection point (IoC) of FastAPI. It automatically allocates the database connection pool (SQLAlchemy Session) and Redis client pulled from the global application state (`app.state`) on demand, and then instantiates the required Services and Repo instances downwards, guaranteeing request isolation.
- **Service Lifecycle Management (`app/core/lifespan.py`)**: Centrally takes over the system startup and shutdown logic. Establishes various asynchronous connection pools at once, mounts the logging system, instantiates rate limiters, and initializes all downloaded LLM clients and local Prompt assets, achieving a graceful start and stop.

---

## 2. Domain Services

This project splits multiple focused microservice modules according to Domain-Driven Design (DDD), which work together cooperatively under loose coupling. For the detailed functions and configuration guides of each module, please consult their independent documentation:

1. **[Auth Service](./app/auth_service/README.md)**  
   Provides a complete authentication closed loop covering registration, verification, login, JWT double Token issuance and refreshing, and password reset. Also provides global request rate limiting standards.
2. **[Chat Service](./app/chat_service/README.md)**  
   Centrally manages the connection pools of diverse LLM clients like OpenAI, Gemini, Qwen, encapsulates the streaming event communication protocol, and provides registration capabilities for local Function Calling Tools.
3. **[Subscription Service](./app/subscription_service/README.md)**  
   Acts as the single source of truth for system business logic, uniformly defining the base billing rates for various LLMs and the quotas, discounts, and access permissions of different commercial plans (Free, Pro, etc.).
4. **[Session Service](./app/session_service/README.md)**  
   Responsible for connecting the upper and lower business layers, taking over users' chat histories. Uses Redis + double-write Buffer persistence to drastically optimize database I/O latency. Internally integrates a dynamic loading system for system default Prompts based on YAML Markdown.

---

## 3. Data Flow

The data flow of a typical advanced interactive request (e.g., a user querying a streaming LLM) is as follows:

1. **[Request Reception & Trace Marking]**  
   An HTTP request enters FastAPI, `TelemetryMiddleware` immediately generates a Trace Root, and binds this `trace_id` downwards to all Logs generated during this request.
2. **[Identity Verification & Rate Limiting Guard]**  
   The middleware and `dependencies.py` read the Token, and parse the `user_id` via `Auth Service`. If the API access frequency limit is exceeded, it will be intercepted by `limiter.py`.
3. **[Environment Assembly]**  
   FastAPI dynamically assembles a `SessionService` containing the correct DB/Redis Session through dependency injection.
4. **[Context Local Reconstruction]**  
   `SessionService` attempts to read the user's history from Redis according to the `session_id`; if there's a cache miss, it loads from the PG database with a lock.
5. **[Commercial Permission Ruling]**  
   `SessionService` queries the `SubscriptionService` for the user's current commercial plan to obtain the permitted model types, discount parameters, and the whitelist of available Tools.
6. **[AI Chat & Engine Dispatch]**  
   The fully assembled Payload is handed over to `ChatService`. A Provider in `ChatService` uses the connection pool to request the corresponding third-party LLM interface (and intercepts potential Function Call callbacks midway).
7. **[Streaming Return & Async Buffer Persistence]**  
   The engine throws streaming binary chunks outward back to the client (guaranteeing extremely low latency). Only after the entire stream transmission is complete, the background will execute a double-write into the Redis Buffer via `SessionService`. If the Buffer is full, a `persist_session_buffer_task` will be dispatched to Taskiq to execute database persistence.

---

## 4. Extensibility

The extensibility of this scaffold has the following advantages:

- **Adding New External Models**: Simply expand a new Provider subclass in `ChatService` and register the configuration, then indicate the unit price in the `MODEL_REGISTRY` of `SubscriptionService` for plug-and-play use.
- **Highly Extensible Background Async Ecosystem**: Taskiq natively supports RabbitMQ or Redis as a Broker. If adding time-consuming tasks like sending emails or periodic bill cleaning, directly write the code using the `@broker.task` decorator, and call `.kiq()` to enjoy non-blocking distributed execution and continuous trace log features.
- **Custom Persona Hot-Updating**: To create a specialized "Smart Analysis Agent" for a specific domain, just add a Markdown file in the corresponding folder of `SessionService` and fill in the specific scenario attributes. It will be ready to use on the next process startup.
