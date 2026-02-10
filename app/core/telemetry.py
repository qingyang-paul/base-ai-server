from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import TelemetryConfig


def setup_telemetry(config: TelemetryConfig, app: FastAPI) -> TracerProvider:
    """Telemetry 启动入口：注册 Resource，配置 exporter 和 processor，自动插桩。"""
    # 1. 注册 Resource
    resource = Resource.create({SERVICE_NAME: config.service_name})

    # 2. 配置 OTLP gRPC exporter
    exporter = OTLPSpanExporter(
        endpoint=config.exporter_endpoint,
        insecure=config.insecure,
    )

    # 3. 声明 BatchSpanProcessor 保障性能
    processor = BatchSpanProcessor(exporter)

    # 4. 创建并设置 TracerProvider
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # 5. 自动插桩 FastAPI
    FastAPIInstrumentor().instrument_app(app)

    return provider


def shutdown_telemetry(provider: TracerProvider) -> None:
    """关闭 TracerProvider，刷新并清理所有待发送的 span 数据。"""
    provider.shutdown()