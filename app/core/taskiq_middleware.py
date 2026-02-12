from contextvars import ContextVar
from typing import Optional, Dict

from taskiq import TaskiqMessage, TaskiqResult, TaskiqMiddleware
from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode
from opentelemetry.context import attach, detach, Context

_curr_span = ContextVar("curr_span", default=None)
_curr_token = ContextVar("curr_token", default=None)

class OpentelemetryMiddleware(TaskiqMiddleware):
    def __init__(self, tracer_name: str = "taskiq"):
        self.tracer = trace.get_tracer(tracer_name)

    async def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        # Inject current context into message labels
        carrier: Dict[str, str] = {}
        propagate.inject(carrier)
        for k, v in carrier.items():
            message.labels[f"otel:{k}"] = v
        return message

    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        # Extract context from labels
        carrier = {
            k[5:]: v 
            for k, v in message.labels.items() 
            if k.startswith("otel:")
        }
        ctx: Context = propagate.extract(carrier)
        
        # Start span with extracted context (parent)
        span = self.tracer.start_span(
            name=f"taskiq.execute.{message.task_name}",
            kind=trace.SpanKind.CONSUMER,
            context=ctx,
            attributes={
                "taskiq.task_id": message.task_id,
                "taskiq.task_name": message.task_name,
            }
        )
        
        # Make this span active in the current context
        token = attach(trace.set_span_in_context(span))
        
        # Store span and token in ContextVars to access in post_execute/on_error
        _curr_span.set(span)
        _curr_token.set(token)
        
        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
    ) -> None:
        span = _curr_span.get()
        token = _curr_token.get()
        
        if span:
            if result.is_err:
                span.set_status(Status(StatusCode.ERROR, str(result.error)))
                if isinstance(result.error, BaseException):
                    span.record_exception(result.error)
            else:
                span.set_status(Status(StatusCode.OK))
            span.end()
        
        if token:
            detach(token)
            
        _curr_span.set(None)
        _curr_token.set(None)

    async def on_error(
        self,
        message: TaskiqMessage,
        exception: BaseException,
    ) -> None:
        span = _curr_span.get()
        token = _curr_token.get()
        
        if span:
            span.record_exception(exception)
            span.set_status(Status(StatusCode.ERROR, str(exception)))
            span.end()
            
        if token:
            detach(token)
            
        _curr_span.set(None)
        _curr_token.set(None)
