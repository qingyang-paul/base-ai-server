# Subscription Service

目标：
1. 管理订阅套餐的配置
2. 管理用户订阅信息

使用注意：
内部服务：
1. `gemini` 的provider统一写成 `gemini` 而不是 `google`, 这涉及全局字段转换
2. 数据库 `core/model.py` ，有外键约束，还没补充
3. Subscription Service 的 core/config.py 是直接在config.py 中配置，没有读取环境变量

外部服务：
1. 订阅套餐配置里，有allowed_tools 字段，需要在Chat Service/core/tool_manager.py 中进行工具的注册和管理(详情参阅chat_service/README.md)
2. signup 验证邮箱后，需要触发 SubscriptionService.create_subscription 方法
3. SubscriptionService.process_message_billing() 需要Session Message Schema
4. `app/core/lifespan.py` 里，taskiq的任务注册要比broker的启动更早，否则会报错