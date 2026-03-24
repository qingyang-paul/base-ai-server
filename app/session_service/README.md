# Session Service

## 1. Module Overview

The Session Service is at the core of the application layer, responsible for connecting the frontend user's session context (Session Context), the underlying LLM session (Chat Service), and the user's billing/permission system (Subscription Service). Specifically, it is mainly responsible for the following three parts:

1. **Session Status and History Management (Session & Context Management)**
   - Takes over all user Chat Sessions, responsible for creating and updating Session Meta information.
   - Manages the storage and reading of long contexts. To ensure high-performance streaming responses, it adopts a **Redis Cache + Buffer mechanism** combined with the underlying PostgreSQL for persistence.
2. **System Prompt Dynamic Management (System Prompt Registry)**
   - Provides a Prompt management system with hot-loading capability and even in-memory O(1) reading. Enables seamless management of system personas and versions through Markdown files annotated with `yaml` frontmatter.
3. **Request Assembly and Permission Checking (Payload Builder & Permission Check)**
   - Every time a user asks a question, Session Service is responsible for querying Subscription Service to obtain the current user's subscription plan.
   - Based on the available model list and available tools (Tools) configured in the plan, it validates and builds the final `GenerationConfig` and `LLMPayload` to send to the Chat Service.

---

## 2. Core Mechanism Parse

### 2.1 Prompt Registration and Loading Mechanism (`prompt_registry.py`)

All System Prompts are centrally stored as `.md` files in the `app/session_service/core/system_prompts` directory.

- **File Specification**: The top of the file must contain YAML Frontmatter describing the `scene` (e.g., `pal`), `version` (e.g., `v1.0`), and `description`.
- **Memory Residence**: When the App starts, it loads and reads all file contents into memory via the `initialize()` singleton, avoiding runtime disk I/O. When the service updates a Prompt, it simply adds a new Markdown file; after code reload, the system will automatically adopt the new persona through version comparison (`get_latest_prompt`).

### 2.2 Redis Cache and Double-Write Buffer Mechanism

To combat the latency bottlenecks caused by database I/O and maintain extreme TTS (Time To First Token) response, the Session Service implements an intelligent double-write buffering strategy:

- **Read Cache**: Session records are preferentially read from `session_cache:{session_id}`. On a cache miss, it triggers a distributed lock (`lock:session:{session_id}`) to load on-demand from Postgres.
- **Write Buffer (`SESSION_BUFFER_THRESHOLD`)**: Generated messages are not immediately written to Postgres. Instead, they are first written strictly into the Redis Buffer queue. Only when the backlog of messages in the Buffer exceeds the `SESSION_BUFFER_THRESHOLD` (default 50) in `config.py` will it dispatch the `persist_session_buffer_task` asynchronous Taskiq task for bulk database persistence (Persist to DB).

---

## 3. Extension and Configuration Guide

When you need to perform secondary development or add new features for the Chat module, you will most likely need to touch the following configuration points:

### 3.1 Adding a New Digital Persona/New Prompt Scene

1. **Define Scene Enum**: Add a new enum in `SystemPromptScene` of `app/session_service/core/prompt_registry.py` (e.g., `DATA_ANALYST = "data_analyst"`).
2. **Create Prompt File**: Add a new `.md` file under the `app/session_service/core/system_prompts/` folder, writing the Frontmatter, for example:

   ```yaml
   ---
   scene: data_analyst
   version: v1.0
   description: Specialized prompt for data analysis
   ---
   You are an expert Data Analyst. ...
   ```

   The next time the service starts, this Prompt will be taken over and used as the latest version of the `DATA_ANALYST` scene.

### 3.2 Adjusting Session Parameter Thresholds

In `app/session_service/core/config.py`, you can modify configurations aimed at performance stacking:

- `SESSION_INACTIVE_THRESHOLD`: (Default 300s) How long a session is inactive before it is considered expired or needs cleaning.
- `SESSION_BUFFER_THRESHOLD`: (Default 50 items) Controls how many records are accumulated in memory before dispatching a bulk persistence Taskiq task; moderately increasing this can reduce the number of database transactions.

### 3.3 Tool/Context Association Pass-Through

The current code reserves `context_kwargs = {"user_id": str(user_id)}` to be injected into the underlying toolchain in `handle_agent_stream_reply`. If your newly developed Function Tool requires the user's geolocation, language preference, etc., please insert the parameters directly into this dictionary to pass them downstream after the `SessionService` receives the request.
