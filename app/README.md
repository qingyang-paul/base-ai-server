# Base Infra

2026.2.10


## Level 1

/core/config.py
1. logger 是否使用JSON格式输出
2. telemetry 的Resource参数，接收地址参数

/core/logger.py:
1. 拦截server的logging信息
2. 上下文抓取otel trace_id
3. 自定义sink函数组装json格式信息
4. setup_logger启动入口

/core/telemetry.py:
1. 注册resource
2. 配置打印位置
3. 声明批处理 保障性能
4. 自动插桩，监控服务调用

/core/lifespan.py:
1. 管理logger和telemetry


/test
1. 启动logger和telemetry，保证正常启动
2. 在代码中插入log，调用外部服务(testcontainer)，检查打印的log信息


## Level 2

/core/config.py
1. 定义redis初始化相关的参数Schema
2. 定义postgres初始化相关的参数Schema

/core/redis.py:
1. redis连接池初始化
2. redis连接池关闭
3. redis连接获取与释放

/core/postgres.py:
1. postgres连接池初始化
2. postgres连接池关闭
3. postgres连接获取与释放

/core/lifespan.py
1. 管理redis和postgres连接池的启动和关闭

/dependency.py
1. redis实例的拿取工具
2. postgres实例的拿取工具

/api/v1/core/endpoints/health.py
1. 建立GET接口，检查redis和postgres的健康状况

/core/exceptions.py
1. 定义数据库连接相关的错误类别

/core/error.py
1. exceptions映射到FastAPI Server层面，数据库等内容服务宕机，统一返回模糊信息

/test
1. 启动redis和postgres连接池，保证正常启动
2. 使用testcontainer模拟测试，看连接池返回的实例能否正常操作
3. 检查heath.py的接口，能否如期反应数据库的连接情况

