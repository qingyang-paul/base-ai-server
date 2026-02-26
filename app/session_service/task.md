# Session Service

2026.2.24

**目标**：管理聊天session 的相关信息。

**场景**：用户发起单轮Chat之前，需要有上下文；Chat之后，需要信息持久化



## 全局信息

1. **日志**: `app/core/logger.py`
2. **异常**: `session_servic/core/exceptions.py` 自定义异常
3. **运行**: `uv` 管理环境、运行脚本
4. **异步**: 所有服务都是异步服务（task中可能没写，但实现时要补充）
5. **日志**: 书写良好的日志和注释
6. **依赖**: `app/dependencies.py` 里有数据库session的依赖，`app/core/lifespan.py` 也是。在修改全局依赖的时候，先检查是不是已经存在了。
7. **AuthMiddleware**: `auth_service/core/middleware.py` 
8. **rate_limiter**: `auth_service/core/limiter.py`
9. **get_current_user_id**: `app/dependencies.py`



## level 1: DTO配置

### Config

```python
# session_service/core/config.py


# session冷却多久可以认为是inactive
session_inactive_threshold: int

# session buffer 达到多少条消息主动做持久化
session_buffer_threshold: int 

```

### Prompts Registery

```python
# session_service/core/prompt_registry.py

class SystemPromptScene(str, Enum):
  PAL="pal"
  SESSION_TITLE="session_title"
  SESSION_COVER="session_cover"

# System Prompt 注册表：
	# system prompt 要有一个专门的文件夹去维护 session_service/core/system_prompts/
  # 在config里有一个注册表，去建立对应关系，方便快速索引system prompts
class PromptMeta(BaseModel):
    scene: SystemPromptScene     
    version: str        # 版本号，例如: "1.0.0"
    description: str    # 内部备注：这个版本的 Prompt 改了什么
    content: str  # 【核心改进】：把读取到的文本内容直接驻留在内存！
    



class PromptRegistry:
    _registry: Dict[str, PromptMeta] = {}
    _is_initialized: bool = False

    @classmethod
    def initialize(cls, prompts_dir: str = "session_service/core/system_prompts"):
        """启动时调用：自动扫描并注册所有 Prompt"""
        if cls._is_initialized:
            return

        base_path = Path(prompts_dir)
        if not base_path.exists():
            return
            
        # 遍历目录下所有 .md 文件
        for file_path in base_path.rglob("*.md"):
            cls._parse_and_register(file_path)
            
        cls._is_initialized = True
        print(f"✅ 优雅加载了 {len(cls._registry)} 个 System Prompts.")

    @classmethod
    def _parse_and_register(cls, file_path: Path):
        """解析带有 YAML Frontmatter 的 Markdown 文件"""
        content = file_path.read_text(encoding="utf-8")
        
        # 简单的 Frontmatter 解析逻辑
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_meta = yaml.safe_load(parts[1])
                body = parts[2].strip()
                
                meta = PromptMeta(
                    scene=SystemPromptScene(yaml_meta["scene"]),
                    version=str(yaml_meta["version"]),
                    description=yaml_meta.get("description", ""),
                    content=body  # 将文本存入内存
                )
                
                key = f"{meta.scene.value}:{meta.version}"
                cls._registry[key] = meta

    @classmethod
    def get_prompt_content(cls, scene: SystemPromptScene, version: str) -> str:
        """获取具体的 Prompt 文本内容，O(1) 内存读取，无磁盘 I/O"""
        key = f"{scene.value}:{version}"
        if key not in cls._registry:
            raise ValueError(f"Prompt {key} not found!")
        return cls._registry[key].content
		
    @classmethod
    def get_latest_prompt(cls, scene: SystemPromptScene) -> PromptMeta:
        """获取指定场景下的最新版本 Prompt"""
        
        # 1. 过滤出该场景下的所有 Prompt
        scene_prompts = [
            meta for meta in cls._registry.values() 
            if meta.scene == scene
        ]
        
        if not scene_prompts:
            raise ValueError(f"No prompts registered for scene: {scene}")

        # 2. 定义版本号解析逻辑 (解决 v1.10 > v1.2 的比较问题)
        def parse_version(version_str: str) -> tuple:
            # 去除前缀 'v' 或 'V' (如果有的话)
            clean_v = re.sub(r'^[vV]', '', version_str)
            # 按点分割并转为整数元组: "1.10" -> (1, 10), "1.2" -> (1, 2)
            try:
                return tuple(map(int, clean_v.split('.')))
            except ValueError:
                # 兼容无法解析为数字的版本号（如 "v1.0-beta"），做降级处理
                return (0,) 

        # 3. 使用 max() 结合自定义排序键选出最大版本
        latest_meta = max(scene_prompts, key=lambda x: parse_version(x.version))
        
        return latest_meta
      
# 初始化注册表
PromptRegistry.register(PromptMeta(
    scene=SystemPromptScene.PAL
    version="v1.0", 
    file_path="pal/v1.0.txt",
    description="初始版本的聊天人设"
))

```



### Schema

```python
# session_service/core/schema.py

class SessionStatus(str, Enum):
	ACTIVE = "active"
  ARCHIVED = "archived"
  DELETED = "deleted"


class SessionMeta(BaseModel): # Redis 存一份 
 
  
  user_id: UUID
  session_id: UUID
  title: Optional[str] = None      # 会话标题
  created_at: datetime             # 创建时间
  updated_at: datetime # 多端校验同步
  llm_choice: str # api router 携带参数
  message_seq_id: int # 最后一条消息的session内seq数
  status: SessionStatus           # 状态管理 active, archived, deleted
  prompt_scene: SystemPromptScene    # 记录这个会话是干嘛的 (e.g., "default_chat")
  prompt_version: str  # 记录这个会话【创建时】使用的 prompt 版本 (e.g., "v1.0")
  
class SessionMessage(BaseModel): # 
  user_id: UUID
  session_id: UUID
  created_at: datetime
  seq_id: int # session内的自增数
  llm_message: LLMMessage # import from chat_service/core/schema.py

  
```

### Model

#### Redis

```python
# key: session_meta:{session_id}
class SessionMeta(BaseModel): # Redis 存一份 
 
  user_id: UUID
  session_id: UUID
  title: Optional[str] = None      # 会话标题
  created_at: datetime             # 创建时间
  updated_at: datetime # 多端校验同步
  llm_choice: str # api router 携带参数
  message_seq_id: int # 最后一条消息的session内seq数
	status: SessionStatus    # 状态管理 active, archived, deleted
  prompt_scene: SystemPromptScene    # 记录这个会话是干嘛的 (e.g., "default_chat")
  prompt_version: str  # 记录这个会话【创建时】使用的 prompt 版本 (e.g., "v1.0")

# key: session_cache:{session_id}
# Zset[SessionMessage] (score: seq_id)

# key: session_buffer:{session_id}
# Zset[SessionMessage] (score: seq_id)

# key: session_seq:{session_id}
# 自增 id
```



#### PG

```python
# session_service/core/model.py

class SessionMessage(Base):
  # restore Session Message
  # 根据SessionMessage Schema 建立就可以
  
class SessionMeta(Base):
  # 根据SessionMeta Schema 建立就可以
  
```

## level 2: Service 配置

```python
# session_service/session_service.py

class SessionService:
  
  async def create_session_meta(
  		self,
    	session_id: UUID,
    	user_id: UUID,
    	prompt_scene: SystemPromptScene,
    	llm_choice: str,
  ):
    # 新建 session 时，插入表信息
    
    pass
  
  
  async def restore_llm_message_in_buffer( 
  				self,
    			session_id: UUID
    			llm_messgaes: List[LLMMessage] 
  ):
    # 调用内部方法，把LLMMessage转化为SessionMessage
    # 存入Redis Buffer 和Cache
    
  async def _translate_session_messages_to_llm_messages(
  		self,
    	session_messages: List[SessionMessage]
  )-> List[LLMMessage], 
			# 去除多余信息，返回一个ChatService能直接用的消息列表
      pass
  
  
  async def _translate_llm_messages_to_session_messages(
  	self, 
    llm_messages: List[LLMMessage],
    session_id: UUID,
  	)->List[SessionMessage]:
  		# 补充必要的信息，返回SessionService能直接用的消息列表
      # 关于seq_id: 直接调用 Redis 的 INCR session_seq:{session_id}
      pass
    
  async def load_session_context_to_redis(
  	self,
    session_id: UUID
  ):
    # 从PG拿session的历史会话，
    # 先看是否需要同步（最后一个seq_id是否匹配）
    # 全量redis session_cache:{session_id}
    # 替换session_cache的过程，要保证没有读写: 引入分布式锁（可以使用 Redis 的 SETNX 或现成的 Redlock 库）
    # 伪代码思路
      async with redis.lock(f"lock:session:{session_id}", timeout=5):
          # 1. 检查 Redis 里最后一个 seq_id
          # 2. 从 PG 查询比它大的增量数据，或者全量拉取
          # 3. Pipeline 批量写入 session_cache
          pass
  
	async	def build_llm_payload(
      self,
    	system_prompt_scene：SystemPromptScene, # 单独管理，有一个注册表
    	session_id,
    
    ) -> LLMPayload： # LLMPayload: import from ChatService
    
    
      # 组装 chat_history: ChatHistory, # ChatHistory: import from ChatService
      # 组装 user_query: UserQuery, 		# UserQurey: import from ChatService
      # 组装 session_context: SessionContext,  # SessionContext: import from ChatService
			# 工具：在subscription_service/core/config 里，每个套餐都有对应配置好的工具
     	# 调用ChatService.build_llm_payload()
    # 返回 Payload
	
  async def build_llm_generation_config(
  		self,
    	user_id: UUID,
     	llm_choice: str
  ) -> GenerationConfig:
    # 检查用户的模型权限
    pass
  
    	
   async def handle_agent_stream_reply(
      self, 
      user_query_text: str,
      session_id: UUID,  # 需要知道是哪个 session
      user_id: UUID
  ) -> AsyncGenerator[StreamReply, None]: # import from chat_service/core/schema.py

      # 1. 加载 & 校验上下文 (带锁，防止并发加载重入)
      await self.load_session_context_to_redis(session_id)

      # 2. 获取 Meta，处理 Prompt Version (新会话用最新，老会话沿用)
      meta = await self.get_session_meta(session_id)
      system_prompt = PromptRegistry.get_prompt(meta.prompt_scene, meta.prompt_version)

      # 3. 构造下游参数
      generation_config = await self.build_llm_generation_config(user_id, meta.llm_choice)
      llm_payload = await self.build_llm_payload(system_prompt, session_id, user_query_text)

      user_message = ...
      # 4. 调用底层 ChatService 拿到流
      # 注意：这里 ChatService 只管生流，不负责存数据！

      # ... 前置组装逻辑 (生成 User 的 LLMMessage) ...

        
        # 调用底层
        stream_gen = self.chat_service.chat_stream_with_tools(...)
        
        all_new_messages_to_save: List[LLMMessage] = []
        
        async for reply in stream_gen:
            if reply.event_type == StreamEventType.TEXT_CHUNK:
                yield reply # 直接透传给前端
                
            elif reply.event_type == StreamEventType.TOOL_CALL:
                yield reply # 透传给前端，让前端显示 loading 动画
                
            elif reply.event_type == StreamEventType.RUN_FINISH:
                # 拿到了 ChatService 内部产生的包含 Tool Call 和 Tool Result 的所有消息！
                all_new_messages_to_save.extend(reply.new_messages)
                break
                
        # 此时流已断开，前端已经接收完文本。
        # SessionService 开始独立执行转换和持久化！
        # 聊天结束落库时，也必须抢锁！
        async with self.repo.redis.lock(lock_key, timeout=5):
        await self._translate_and_save_to_buffer(
            session_id=session_id,
            llm_messages=all_new_messages_to_save
        )

	
```



## level 3: Repo 配置

```python
# session_service/session_repo.py

class SessionRepo:
  
  class SessionRepo:
    def __init__(self, redis_client, db_session):
        self.redis = redis_client
        self.db = db_session  # SQLAlchemy async session

    # ==================== Redis 操作 ====================

    async def get_next_seq_ids(self, session_id: UUID, increment: int = 1) -> int:
        """
        原子获取下一个 seq_id。
        如果本次有 3 条消息要存，传入 increment=3，返回最大的 seq_id，
        方便上层给每条消息倒推分配 seq_id。
        """
        key = f"session_seq:{session_id}"
        return await self.redis.incrby(key, increment)

    async def save_new_messages_pipeline(
        self, 
        session_id: UUID, 
        messages: List[SessionMessage],
        latest_meta: SessionMeta  # 用于同步更新 updated_at 和 message_seq_id
    ):
        """
        【核心方法】使用 Pipeline 保证 Cache、Buffer、Meta 的原子写入
        """
        cache_key = f"session_cache:{session_id}"
        buffer_key = f"session_buffer:{session_id}"
        meta_key = f"session_meta:{session_id}"

        # 构造 Zset 需要的 mapping: { JSON字符串: score(seq_id) }
        zset_mapping = {
            msg.model_dump_json(): msg.seq_id for msg in messages
        }

        pipeline = self.redis.pipeline()
        
        # 1. 写入 Cache (ZADD)
        pipeline.zadd(cache_key, zset_mapping)
        
        # 2. 写入 Buffer (ZADD)
        pipeline.zadd(buffer_key, zset_mapping)
        
        # 3. 更新 Meta
        pipeline.set(meta_key, latest_meta.model_dump_json())

        # 批量执行
        await pipeline.execute()

    async def get_session_meta_from_redis(self, session_id: UUID) -> SessionMeta | None:
        """从 Redis 获取会话元数据"""
        data = await self.redis.get(f"session_meta:{session_id}")
        return SessionMeta.model_validate_json(data) if data else None

    async def delete_session_buffer_by_score(self, session_id: UUID, range_start: int, range_end: int):
        """
        消费 Buffer 后删除记录
        Redis ZREMRANGEBYSCORE: 默认是闭区间 [start, end]
        如果想要 [start, end) 排除 end，给 max 加上 '(' 即可
        """
        key = f"session_buffer:{session_id}"
        # 例如 range_start=1, range_end=10 -> max_score = "(10"
        max_score = f"({range_end}" 
        await self.redis.zremrangebyscore(key, min=range_start, max=max_score)

    async def get_session_cache_messages(self, session_id: UUID, limit: int = 50) -> List[SessionMessage]:
        """从 Redis 获取最近的 N 条上下文"""
        key = f"session_cache:{session_id}"
        # ZREVRANGE 获取最新的 N 条，再反转回正序
        pass 

    # ==================== PostgreSQL 操作 ====================

    async def insert_session_messages_to_alchemy(self, messages: List[SessionMessage]):
        """异步落库 Worker 调用：将一批消息写入 PG"""
        # 将 DTO 转换为 SQLAlchemy Model 后 add_all() 并 commit()
        pass

    async def read_session_messages_from_alchemy(self, session_id: UUID, limit: int = 50) -> List[SessionMessage]:
        """当 Redis Cache 丢失或用户翻阅历史时，从 PG 兜底读取"""
        pass
  
  	async def create_session_meta_to_alchemy(self, session_meta: SessionMeta):
      	""" 新建一个session meta 信息 """
      	pass
      
     async def read_session_meta_from_alchemy(self, session_id):
      	""" 从PG兜底读取 """
        pass
      
      async def update_session_meta_to_alchemy(
        self, 
        session_meta_update: SessionMetaUpdateSchema):
        """ 从PG更新SessionMeta """
        pass
      
    # ==================== Smart 操作 ====================
    # 对于Service来说，并不在乎是从哪里读取的信息，这里要写统一读取接口
    

    async def smart_get_session_meta(self, session_id: UUID) -> SessionMeta | None:
            meta = await self.get_session_meta_from_redis(session_id)
            if meta:
                return meta

            meta = await self.read_session_meta_from_alchemy(session_id)
            if meta:
                # 查到后直接回写 Redis，【不设置 TTL】，等待 Worker 审判
                await self.redis.set(
                    f"session_meta:{session_id}", 
                    meta.model_dump_json()
                )
            return meta

        async def smart_get_session_context(self, session_id: UUID, limit: int = 50) -> List[SessionMessage]:
            messages = await self.get_session_cache_messages(session_id, limit)
            if messages and len(messages) > 0:
                return messages

            messages = await self.read_session_messages_from_alchemy(session_id, limit)
            if messages:
                pipeline = self.redis.pipeline()
                cache_key = f"session_cache:{session_id}"
                seq_key = f"session_seq:{session_id}"

                zset_mapping = {msg.model_dump_json(): msg.seq_id for msg in messages}
                pipeline.zadd(cache_key, zset_mapping)

                max_seq = max(msg.seq_id for msg in messages)
                pipeline.set(seq_key, max_seq)


                await pipeline.execute()

            return messages


```



## level 4: 测试

单元测试：测试Service和Repo的函数逻辑

集成测试：测试service调用repo的数据流转、最终结果是否符合预期

## level 5: Lifespan 和 Dependencies 配置

`app/core/lifespan.py`:  prompt registry 

```python
PromptRegistry.initialize("session_service/core/system_prompts")
```



`app/dependencies.py`: Session_service, session_repo





## level 6: API Router 配置

```python
# app/api/v1/session/endpoints/

class ChatRequest(BaseModel):
  	user_query: str,
  	llm_choice: str,

@AuthMiddleware # auth_service/core/middleware.py, app/main.py
@limiter
@get_current_user_id (Dependency injection)
@router.post("{session_id}/chat")
async def chat_with_agent(
	
  
):
  # ..
  

```



## level 7: 集成测试

测一下router的逻辑

## level 6: Taskiq Tasks

```python
# task 1:
# 定时任务，找已经不再活跃的session，完成剩余的持久化工作

# 不再活跃的判断逻辑：updated_at 和当前时间的比较，超过threshold(session_service/core/config.py)

# 持久化逻辑：先确定seq_id range, 搬运到Postgres, 然后在 session_buffer 里把对应范围的消息删除

# 如果buffer消息处理后为空，可以把session_buffer session_cache session_meta 删除掉

# 并发控制：在找非活跃session的时候，加锁，保证每个worker找到的session不一样
# 在锁定 buffer range 的时候，要加锁，保证只有一个地方在修改buffer
# 在删除 session 相关信息的时候，要加锁，保证无法读


# ==================== Task 1: 定时清扫任务 ====================

@broker.task(schedule=[{"cron": "*/5 * * * *"}]) # 每 5 分钟执行一次
async def cleanup_inactive_sessions_task(
    repo: SessionRepo = TaskiqDepends(get_session_repo)
):
    """
    Task 1: 定时任务。找出不活跃的 session，兜底持久化，并清理 Redis。
    """
    # 1. 遍历所有的 session_meta key
    # 使用 scan_iter 防止一次性 keys() 阻塞 Redis
    async for key in repo.redis.scan_iter(match="session_meta:*"):
        
        # 从 key 中解析出 session_id (格式: session_meta:xxxx-xxxx...)
        session_id_str = key.decode("utf-8").split(":")[1]
        session_id = UUID(session_id_str)
        
        # 获取 meta
        meta = await repo.get_session_meta_from_redis(session_id)
        if not meta:
            continue
            
        # 计算是否 inactive
        now = datetime.now(timezone.utc)
        time_diff = (now - meta.updated_at).total_seconds()
        
        if time_diff > session_inactive_threshold:
            # 💡 【核心：双重检查锁定】
            lock_key = f"lock:session:{session_id}"
            
            # 尝试获取锁，如果获取不到（说明用户恰好在发消息，或者 Task 2 正在落库），则跳过本轮
            lock = repo.redis.lock(lock_key, timeout=10, blocking_timeout=1)
            acquired = await lock.acquire()
            
            if acquired:
                try:
                    # ⚠️ 获取锁后，必须【再次读取】 meta，防止在等待锁的期间被更新了！
                    fresh_meta = await repo.get_session_meta_from_redis(session_id)
                    fresh_time_diff = (now - fresh_meta.updated_at).total_seconds()
                    
                    if fresh_time_diff <= session_inactive_threshold:
                        continue # 刚刚复活了，放弃清理
                    
                    # 2. 兜底持久化剩余的 Buffer (复用 Task 2 的逻辑)
                    messages = await repo.get_session_buffer_messages(session_id)
                    if messages:
                        await repo.insert_session_messages_to_alchemy(messages)
                        await repo.db.commit()
                        
                    # 3. Buffer 清空后，彻底删除 Redis 里的 Session 痕迹
                    pipeline = repo.redis.pipeline()
                    pipeline.delete(f"session_meta:{session_id}")
                    pipeline.delete(f"session_cache:{session_id}")
                    pipeline.delete(f"session_buffer:{session_id}")
                    pipeline.delete(f"session_seq:{session_id}")
                    await pipeline.execute()
                    
                    print(f"🧹 Cleaned up inactive session {session_id}")
                    
                finally:
                    # 确保锁被释放
                    await lock.release()
```

```python
# task 2:主动触发任务

# 由 service 在流式返回时显式调用，触发条件是buffer数量达到threshold

# 持久化流程： 1. 锁定buffer message range; 2. 搬运到Postgres; 3. 删除Redis buffer 对应的信息

# 注意防止并发：在处理buffer range的时候要保证只有一个地方在处理这些buffer messages


# ==================== Task 2: 主动触发任务 ====================

@broker.task
async def persist_session_buffer_task(
    session_id: UUID,
    repo: SessionRepo = TaskiqDepends(get_session_repo)
):
    """
    Task 2: 主动触发。当 Service 发现 buffer 达到 threshold 时调用。
    使用方法: await persist_session_buffer_task.kiq(session_id)
    """
    lock_key = f"lock:session:{session_id}"
    
    # 1. 锁定特定 Session 的操作
    # timeout 设置一个合理的值(如 10s)，防止 worker 崩溃导致死锁
    async with repo.redis.lock(lock_key, timeout=10):
        # 2. 读取当前 buffer 里的所有消息
        buffer_key = f"session_buffer:{session_id}"
        
        # 获取所有 buffer 消息（按 seq_id 从小到大排序）
        # 这里需要 Repo 提供一个获取 buffer 原始数据的方法
        messages = await repo.get_session_buffer_messages(session_id) 
        
        if not messages:
            return # 已经被其他 worker 处理过了，直接返回
            
        # 3. 确定 range (取这批消息的最小和最大 seq_id)
        min_seq_id = messages[0].seq_id
        max_seq_id = messages[-1].seq_id
        
        # 4. 搬运到 Postgres
        await repo.insert_session_messages_to_alchemy(messages)
        await repo.db.commit() # 别忘了 commit!
        
        # 5. 删除 Redis buffer 对应范围的消息
        # 注意：这里使用 range 删除，而不是直接 DEL buffer，
        # 是为了防止在落库期间有极端的插入（虽然有锁，但防御性编程更安全）
        await repo.delete_session_buffer_by_score(
            session_id=session_id, 
            range_start=min_seq_id, 
            # 注意开闭区间，如果 Repo 内部做了处理，这里直接传 max_seq_id 即可
            range_end=max_seq_id + 1 
        )
        print(f"✅ Successfully persisted buffer for session {session_id} (seq: {min_seq_id}-{max_seq_id})")

```




