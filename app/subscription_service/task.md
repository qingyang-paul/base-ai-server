# SubscriptionService

2026.02.19

> 目标：管理订阅

场景：

记录用户的付费等级、更新用户的付费等级、配置等级下的LLM权限

## 全局信息

1. **日志**: `app/core/logger.py`
2. **异常**: `subscription_servic/core/exceptions.py` 自定义异常
3. **运行**: `uv` 管理环境、运行脚本
4. **异步**: 所有服务都是异步服务（task中可能没写，但实现时要补充）
5. **日志**: 书写良好的日志和注释
6. **依赖**: `app/dependencies.py` 里有数据库session的依赖，`app/core/lifespan.py` 也是。在修改全局依赖的时候，先检查是不是已经存在了。

## level 1: 等级配置

```python
# subscription_service/core/config.py

# 定义业务层级规则
  
# ==========================================
# 1. 全局模型注册表 (Single Source of Truth)
# ==========================================
class GlobalLLMConfig(BaseModel):
    model_id: str
    provider: Literal['openai','anthropic', 'gemini'] 
    base_prompt_ratio: float = Field(..., description="基准输入费率")
    base_completion_ratio: float = Field(..., description="基准输出费率")
    max_tokens_per_request: int = Field(default=4096)

# 物理模型只在这里定义一次
MODEL_REGISTRY: Dict[str, GlobalLLMConfig] = {

    "gpt-4-turbo": GlobalLLMConfig(
        model_id="gpt-4-turbo", provider="openai",
        base_prompt_ratio=0.01, base_completion_ratio=0.03, max_tokens_per_request=8192
    ),
    "gemini-3-flash-preview": GlobalLLMConfig(
        model_id="gemini-3-flash-preview", provider="gemini",
        base_prompt_ratio=0.015, base_completion_ratio=0.075, max_tokens_per_request=8192
    ),
   "gemini-3-pro-preview": GlobalLLMConfig(
      model_id="gemini-3-pro-preview", provider="gemini",
      base_prompt_ratio=0.015, base_completion_ratio=0.075, max_tokens_per_request=8192
    ),
    "gemini-3.1-pro-preview": GlobalLLMConfig(
      model_id="gemini-3.1-pro-preview", provider="gemini",
      base_prompt_ratio=0.015, base_completion_ratio=0.075, max_tokens_per_request=8192
    )
    # ... 其他模型
}

# ==========================================
# 2. 套餐与权限配置 (Business Logic)
# ==========================================
class PlanConfig(BaseModel):
    name: str
    base_credits: float
    default_model: str = Field(..., description="该套餐默认使用的模型 ID")
    
    # 核心改进 1：只存 Model ID 的列表，不再冗余定义模型参数
    allowed_models: List[str] = Field(..., description="该套餐允许使用的模型 ID 列表")
    
    # 核心改进 2：套餐级别的全局折扣（例如 Pro 用户消耗额度打 5 折）
    global_discount: float = Field(default=1.0, description="扣费折扣率，1.0 为不打折")
    
    # 核心改进 3：(可选) 针对特定模型的特殊定价覆盖
    custom_model_ratios: Optional[Dict[str, Dict[str, float]]] = Field(
        default_factory=dict, 
        description="特例：覆盖特定模型的基础费率"
    )
    
    allowed_tools: List[str] = Field(default_factory=list)

# 商业套餐配置变得极其清爽
PLAN_REGISTRY: Dict[str, PlanConfig] = {
    "free": PlanConfig(
        name="Free Plan",
        base_credits=300, # 每个月的默认配额
        default_model="gemini-3.1-pro-preview",
        allowed_models=["gemini-3-flash-preview", "gemini-3-pro-preview", "gemini-3.1-pro-preview"],
       allowed_tools=[]
    ),
    "pro": PlanConfig(
        name="Pro Plan",
        base_credits=1000, # 每个月的默认配额
        default_model="gemini-3.1-pro-preview",
        allowed_models=["gemini-3-flash-preview", "gemini-3-pro-preview", "gemini-3.1-pro-preview"],
       allowed_tools=[]
    )
}
  
```

```python
# subscription_service/core/model.py

# 用户定义表（Postgres)
class UserSubscriptions(Base):
  __tablename__ = "user_subscriptions"
  id: UUID
  user_id: UUID
  subscription_tier: Literal['free', 'pro']
  current_period_start: datetime # UTC时间
  current_period_end: datetime # UTC时间
  auto_renew: bool # 自动续费
  status: Literal['active', 'canceled', 'past_due', 'trialing'] # 订阅状态：活跃、取消、欠费、试用
  stripe_subscription_id: str # 关联外部支付网关 ID (Stripe/Alipay)
  
# 用户额度表
class UserCreditBalance(Base):
  __tablename__ = "user_credit_balances"
  user_id: UUID
  subscription_credits: Decimal # 套餐内剩余额度（按月清零）
  purchased_credits: Decimal # 用户单独充值的额度（永久有效，不过期）
 updated_at: datetime # 最后更新时间

# 用户额度流水表
class UsageLedger(Base):
    __tablename__ = "usage_ledgers"
    id: UUID
    user_id: UUID
    created_at: datetime
    session_id: UUID
    message_id: UUID
    # 拆分扣费明细
    sub_credits_deducted: Decimal
    purchased_credits_deducted: Decimal
    # 拆分余额快照
    sub_balanced_after: Decimal 
    purchased_balanced_after: Decimal
  
```

```python
# subscription_service/core/schema.py

# 数据流转DTO

    
# ==========================================
# 2. 单个套餐/层级的配置 -> 用于订阅页面的展示
# ==========================================
# 给前端展示用的套餐详情 DTO
class PlanDetailResponse(BaseModel):
    name: str
    base_credits: Decimal
    default_model: str
    allowed_models: List[str] # 告诉前端这个套餐能选哪些模型
    
# ==========================================
# 3. 用户订阅信息 （读 >> 写）
# ==========================================

# 用户当前的会话鉴权上下文 DTO
class UserSubscriptionPlan(BaseModel):
    user_id: UUID
    subscription_plan: str 
    available_credits: Decimal # 注意这里类型要和数据库对齐
    model_choice: str 
    
    # 鉴权逻辑：判断该模型是否在当前套餐的允许名单中
    def can_access_model(self, model_name: str, allowed_models: List[str]) -> bool:
        return model_name in allowed_models
      
      
# ==========================================
# 4. 订阅状态更新载荷 (支持部分更新 Partial Update)
# ==========================================
class UserSubscriptionUpdate(BaseModel):
    """
    用于系统内部或 Webhook 更新用户订阅状态的 DTO。
    所有字段均为 Optional，只有显式传入的字段才会被更新到数据库。
    """
    subscription_tier: Optional[Literal['free', 'pro']] = Field(
        default=None, description="订阅等级 (升级/降级时触发)"
    )
    current_period_start: Optional[datetime] = Field(
        default=None, description="当前计费周期开始时间 (续费成功时更新)"
    )
    current_period_end: Optional[datetime] = Field(
        default=None, description="当前计费周期结束时间 (续费成功时更新)"
    )
    auto_renew: Optional[bool] = Field(
        default=None, description="是否自动续费 (用户主动开启/关闭时更新)"
    )
    status: Optional[Literal['active', 'canceled', 'past_due', 'trialing']] = Field(
        default=None, description="订阅状态 (扣款失败、取消、正常活跃时更新)"
    )
    stripe_subscription_id: Optional[str] = Field(
        default=None, description="绑定的外部支付网关 ID"
    )
    
# ==========================================
# 5. 额度流水创建载荷 (Usage Ledger Create DTO)
# ==========================================
class UsageLedgerCreate(BaseModel):
    """
    用于插入新流水的 DTO，确保财务对账数据的绝对结构化和类型安全。
    """
    user_id: UUID
    session_id: UUID
    message_id: UUID
    
    # 扣费明细
    sub_credits_deducted: Decimal = Field(..., description="本次扣除的套餐额度")
    purchased_credits_deducted: Decimal = Field(..., description="本次扣除的充值额度")
    
    # 扣费后的余额快照（防线）
    sub_balanced_after: Decimal = Field(..., description="扣费后的套餐余额快照")
    purchased_balanced_after: Decimal = Field(..., description="扣费后的充值余额快照")

    # 可选字段：如果数据库层没有设置 default=uuid4 / default=func.now()，可以在这里传入
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None

    

```

## level 2: SubscriptionService

```python
# subscription_service/subscription_service.py

class SubscriptionService:

  
  def calculate_deduction_split(self, 
          required_credits: Decimal, 
          current_sub_credits: Decimal, 
          current_purchased_credits: Decimal) -> dict:
        """
        纯内存计算：优先扣套餐，超出扣充值
        返回: 扣费明细字典，例如 {"sub_deducted": 5, "purchased_deducted": 2, "is_sufficient": True}
        """
        pass
      
      
  def handle_purchase_credit(
    user_id: str,
    purchased_credits: int 
  ):
      # 新购买的credit在这里更新，自主充值的Credit
      pass
    
  

  
  def process_message_billing(self, messages: SessionMessage):
        """
        核心计费入口：从SessionMessage 提取user_id, session_id, token_usage
        """
        # 1. 计算本次需要多少钱 (可以通过 Config 层里的 LLM 费率和 message 的 tokens 算出来)
        required_credits = self._calculate_cost_from_tokens(message)

        # --- 开启数据库事务 (Transaction) ---
        

        # 2. 从 Repo 加锁获取当前余额 (SELECT FOR UPDATE)
            # 这里的 lock_user_balance_for_update 是我们需要在 Repo 层写的方法
          balance_record = self.repo.lock_user_balance_for_update(message.user_id)

        
        # 3. 调用 calculate_deduction_split 计算应该怎么扣
        
        # 4. 如果余额不足，抛出异常或返回失败
        
        # 5. 调用 Repo 更新余额
        
        # 6. 调用 Repo 写入流水 (Ledger)
        
        # --- 提交数据库事务 (Commit) ---
        pass
  
  def handle_subscription_pro(
    user_id: str,
    auto_renew: bool,
    end_at: datetime
  ):
    # 用户订阅更新
    pass
  
  def get_available_credits(
   user_id:str
  )->int:
    # 获得用户订阅+自助购买的credits总数
    pass
  
  def handle_user_cancel_renewal(self, user_id: str):
        """场景 A：用户在前端点击了【取消自动续费】"""
        # 此时只需实例化一个只包含 auto_renew 的 DTO
      payload = UserSubscriptionUpdate(auto_renew=False)
      self.repo.update_user_subscriptions(user_id=user_id, update_payload=payload)
      
      
  def handle_user_registration(self, user_id: UUID):
        """
        处理新用户注册：初始化免费订阅和基础额度
        """
        # 1. 获取系统配置的 Free 套餐基准参数
        free_plan = PLAN_REGISTRY.get("free")
        if not free_plan:
            raise ValueError("系统配置错误：未找到 'free' 套餐定义")

        now_utc = datetime.now(timezone.utc)
        
        # 2. 组装订阅表初始数据
        # 设定首个周期为 1 个月，这样 1 个月后你的 Cron 定时任务就能扫到他并重置额度
        subscription_data = {
            "id": uuid4(),
            "user_id": user_id,
            "subscription_tier": "free",
            "current_period_start": now_utc,
            "current_period_end": now_utc + relativedelta(months=1),
            "auto_renew": False,  # 免费版不需要自动续费（或者根据你的业务逻辑，免费版自动续费即自动重置）
            "status": "active",
            "stripe_subscription_id": "" # 初始为空
        }

        # 3. 组装额度表初始数据
        balance_data = {
            "user_id": user_id,
            "subscription_credits": free_plan.base_credits, # 赠送配置表里写的 base_credits (如 300)
            "purchased_credits": 0,                         # 充值额度默认为 0
            "updated_at": now_utc
        }

        # 4. 执行数据库事务
        try:
            self.repo.create_user_subscription(subscription_data)
            self.repo.create_user_credit_balance(balance_data)
            
            # 统一提交事务，确保两张表同时写入成功
            self.repo.session.commit()
            logger.info(f"成功为新用户 {user_id} 初始化 Free 订阅和额度。")
            
        except Exception as e:
            # 如果任何一步出错（如 user_id 冲突），回滚事务，防止脏数据
            self.repo.session.rollback()
            logger.error(f"为新用户 {user_id} 初始化订阅失败: {str(e)}")
            raise e
```

## levle 3: SubscriptionRepo

```python
# subscription_service/subscription_repo.py

class SubscriptionRepo:
    def lock_user_balance_for_update(self, user_id: str) -> Optional[UserCreditBalance]:
        # 必须带排他锁 (FOR UPDATE)，阻塞其他并发的扣费请求
        pass

    def update_user_credit_balances(self, 
              user_id: str, 
              new_sub_balance: int, 
              new_purchased_balance: int):
        # 执行更新
        pass

    def insert_usage_ledger(self, 
                            ledger_data: UsageLedgerCreate
                            ):
        # 新增一条流水（Insert 而不是 Update）
        pass
        
    def update_user_subscriptions(
       self,
      user_id: UUID,  # 必传：知道要更新哪个用户的订阅
      update_payload: UserSubscriptionUpdate
    ):
        pass
      
     def create_user_subscription(self, subscription_data: dict) -> UserSubscriptions:
        """初始化用户订阅记录"""
        new_sub = UserSubscriptions(**subscription_data)
        self.session.add(new_sub)
        return new_sub

    def create_user_credit_balance(self, balance_data: dict) -> UserCreditBalance:
        """初始化用户额度账户"""
        new_balance = UserCreditBalance(**balance_data)
        self.session.add(new_balance)
        return new_balance
```

## level 4 测试

`subscription_service/tests/`

单元测试+集成测试，试一下 `subscription_service` 和`subscription_repo`是否如我们所想的配合，试一下各个DTO能不能顺利在函数间流转，数据库会不会有问题(使用Test-container)

## level 5 外部链接

1. signup 验证邮箱后（`app/api/v1/auth/endpoints/signup.py`），需要触发 SubscriptionService.create_subscription 方法

2. app/dependencies.py 注册依赖 `SubscriptionService` `SubscriptionRepo`，采用动态生成的方法，而不是单例（Repo依赖Session，Service依赖Repo）

## level 6 异步任务

### 重制订阅计划（定时）

```python
# subscription_service/tasks/reset_expired_subscriptions_and_credits.py
# 重制订阅计划和积分



# 依赖注入获取 DB Session

# 使用标签语法配置 Cron 定时任务：每天 UTC 时间凌晨 0 点执行
@broker.task(schedule=[{"cron": "0 0 * * *"}])
def reset_expired_subscriptions_and_credits():
    """
    扫描并处理所有已到期的订阅
    """
    logger.info("开始执行订阅周期重置与额度刷新任务...")
    
    # 获取数据库会话 
        
        # 1. 查出所有“已到期”且状态还是“活跃”的订阅
        
        
     
                # 获取该用户当前对应的套餐配置（为了知道该送多少 base_credits）
                
                
                # 获取用户的额度账户
               
                # 2. 根据自动续费状态进行分支处理
              
                    # 场景 A：自动续费开启
                    # 注意：在真实的生产环境中，这里应该先调用 Stripe 发起扣款
                    # 只有扣款成功后，才执行以下重置逻辑。这里假设扣款已成功。
                    
                
                    
                    # 推进计费周期（往后加一个月）
                   
                    # 核心：重置周期套餐额度！(充值额度 purchased_credits 保持不动)
                    

                    # 场景 B：自动续费关闭，订阅到期自然失效
                 
                    # 清空套餐额度（因为已经过期了）
              
                # 提交单个用户的事务 (或者你可以选择批量 commit)
                
```

### 初始化订阅信息（用户注册）

```python
# subscription_service/tasks/init_user_subscription.py

@broker.task(task_name="init_user_subscription")
def init_user_subscription_task(user_id_str: str):
    """
    Taskiq Worker 执行的具体任务：为新用户初始化订阅和额度
    """
    user_id = UUID(user_id_str)
    logger.info(f"Taskiq 接收到新用户初始化任务: {user_id}")
    
    # Service 和 Repo 都用依赖注入（用FastAPi 的dependencies，已经在broker里配置过）
    
        
        try:
            # 调用我们刚才写的 Service 核心逻辑
            service.handle_user_registration(user_id=user_id)
        except Exception as e:
            logger.error(f"用户 {user_id} 初始化订阅失败: {e}")
            raise e # 抛出异常让 Taskiq 知道任务失败，触发重试机制
```
