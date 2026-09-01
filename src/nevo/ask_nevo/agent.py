import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from nevo.ai_gateway.entities import ProviderRequest, ProviderResponse
from nevo.ask_nevo.tools import ToolContext, execute_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
"""An unbounded loop against a paid model is a cost incident, not a bug."""

MAX_TOOL_CALLS = 12
"""Total across the whole turn, so a model cannot fan out inside the cap."""


class ToolCapableProvider(Protocol):
    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    text: str
    tool_names: tuple[str, ...]
    iterations: int
    truncated: bool
    response: ProviderResponse


async def run_tool_loop(
    *,
    provider: ToolCapableProvider,
    request: ProviderRequest,
    tool_context: ToolContext,
    max_iterations: int = MAX_TOOL_ITERATIONS,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> AgentOutcome:
    """Run the model until it stops asking for tools, or the caps bite.

    Every tool result goes back as data. Nothing a tool returns is treated as
    instruction, so lesson text or a learner note that happens to read like a
    command cannot redirect the model - and could not widen access even if it
    did, because authorization is re-derived server-side on every call.

    Hitting a cap is not an error: the model is asked once more without tools
    so the user gets the best answer available rather than a failure.
    """
    history: list[dict[str, Any]] = list(request.history)
    used: list[str] = []
    last: ProviderResponse | None = None

    for iteration in range(1, max_iterations + 1):
        current = _with_history(request, history)
        last = await provider.generate(current)

        if not last.tool_calls:
            return AgentOutcome(
                text=last.text,
                tool_names=tuple(used),
                iterations=iteration,
                truncated=False,
                response=last,
            )

        if len(used) + len(last.tool_calls) > max_tool_calls:
            break

        history.append({"role": "assistant", "content": list(last.raw_content)})
        results = []
        for call in last.tool_calls:
            used.append(call.name)
            payload = await execute_tool(tool_context, call.name, call.arguments)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(payload, default=str),
                }
            )
        history.append({"role": "user", "content": results})

    logger.info(
        "Ask Nevo tool loop hit its cap after %d calls; answering without tools",
        len(used),
    )
    final = await provider.generate(_with_history(request, history, drop_tools=True))
    return AgentOutcome(
        text=final.text,
        tool_names=tuple(used),
        iterations=max_iterations,
        truncated=True,
        response=final,
    )


def _with_history(
    request: ProviderRequest,
    history: list[dict[str, Any]],
    *,
    drop_tools: bool = False,
) -> ProviderRequest:
    return ProviderRequest(
        system_instruction=request.system_instruction,
        user_content=request.user_content,
        max_output_tokens=request.max_output_tokens,
        model=request.model,
        cache_prompt=request.cache_prompt,
        tools=() if drop_tools else request.tools,
        history=tuple(history),
    )
