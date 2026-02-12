import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from taskiq import InMemoryBroker

from app.core.taskiq_middleware import OpentelemetryMiddleware

# Setup minimal OTel provider for testing
@pytest.fixture(scope="module")
def tracer():
    provider = TracerProvider(resource=Resource.create({"service.name": "test-service"}))
    # We don't really need exporter, just the provider to create spans
    # provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return trace.get_tracer("test-tracer")

@pytest.mark.asyncio
async def test_trace_propagation(tracer):
    # 1. Setup Broker with Middleware
    broker = InMemoryBroker()
    mw = OpentelemetryMiddleware(tracer_name="test-taskiq")
    mw.set_broker(broker)
    broker.middlewares.append(mw)
    
    # 2. Define a task that captures current trace context
    # We use a list to capture result because tasks run in broker
    captured_trace_id = []
    captured_span_id = []
    
    @broker.task
    async def traced_task():
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            captured_trace_id.append(hex(ctx.trace_id)[2:]) # trace_id is int, convert to hex string
            captured_span_id.append(hex(ctx.span_id)[2:])
        return "done"

    # Start setup
    await broker.startup()

    # 3. Start a parent span and call task
    with tracer.start_as_current_span("parent-span") as parent_span:
        parent_ctx = parent_span.get_span_context()
        parent_trace_id = hex(parent_ctx.trace_id)[2:]
        parent_span_id = hex(parent_ctx.span_id)[2:]
        
        # Send task
        # InMemoryBroker executes immediately in the same loop, but middleware should intercept
        task = await traced_task.kiq()
        result = await task.wait_result()

    # 4. Verify
    assert result.return_value == "done"
    assert len(captured_trace_id) == 1
    
    # The task should have the SAME trace_id as parent
    assert captured_trace_id[0] == parent_trace_id
    
    # The task should be a child, so span_id should be different
    assert captured_span_id[0] != parent_span_id
    
    await broker.shutdown()
