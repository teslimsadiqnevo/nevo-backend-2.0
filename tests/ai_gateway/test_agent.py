"""The tool loop, driven by a scripted provider. No network, no key."""
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from nevo.ai_gateway.agent import run_tool_loop
from nevo.ai_gateway.entities import ProviderRequest, ProviderResponse, ToolCall
from nevo.ai_gateway.privacy import AiPrivacyGuard
from nevo.ask_nevo.directory import DirectoryEntry, PseudonymDirectory
from nevo.ask_nevo.tools import TOOL_SCHEMAS, ToolContext, execute_tool
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.ai_gateway.vocabulary import AiProviderName

AMARA = UUID("aaaaaaaa-0000-4000-8000-000000000001")
OUTSIDER = UUID("bbbbbbbb-0000-4000-8000-000000000009")


class ScriptedProvider:
    """Replays a fixed sequence of provider responses and records requests."""

    def __init__(self, *responses: ProviderResponse) -> None:
        self._responses = list(responses)
        self.requests: list[ProviderRequest] = []

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return _text("Nothing further.")


def _text(body: str) -> ProviderResponse:
    return ProviderResponse(text=body, provider=AiProviderName.CLAUDE, model="test")


def _asks(name: str, arguments: dict) -> ProviderResponse:
    return ProviderResponse(
        text="",
        provider=AiProviderName.CLAUDE,
        model="test",
        tool_calls=(ToolCall(id=f"tu_{name}", name=name, arguments=arguments),),
        raw_content=({"type": "tool_use", "id": f"tu_{name}", "name": name},),
    )


class _EmptyResult:
    def all(self):
        return []


class FakeSession:
    """Enough of AsyncSession for tools that query but find nothing."""

    async def scalars(self, *args, **kwargs):
        return _EmptyResult()

    async def scalar(self, *args, **kwargs):
        return None

    async def get(self, *args, **kwargs):
        return None


def _executor(ctx: ToolContext):
    async def execute(name: str, arguments: dict):
        return await execute_tool(ctx, name, arguments)

    return execute


def _context() -> ToolContext:
    book = PseudonymDirectory(
        (
            DirectoryEntry(
                student_id=AMARA,
                pseudonym=AiPrivacyGuard.pseudonym(AMARA),
                display_name="Amara Okafor",
            ),
        )
    )
    actor = SimpleNamespace(id=uuid4(), school_id=uuid4(), role=UserRole.TEACHER)
    return ToolContext(session=FakeSession(), actor=actor, directory=book)  # type: ignore[arg-type]


def _request() -> ProviderRequest:
    return ProviderRequest(
        system_instruction="You are Ask Nevo.",
        user_content="How is the class doing?",
        max_output_tokens=512,
        tools=tuple(TOOL_SCHEMAS),
    )


async def test_an_answer_with_no_tool_calls_returns_immediately() -> None:
    provider = ScriptedProvider(_text("They are doing well."))

    outcome = await run_tool_loop(
        provider=provider, request=_request(), execute=_executor(_context())
    )

    assert outcome.text == "They are doing well."
    assert outcome.iterations == 1
    assert outcome.tool_names == ()
    assert not outcome.truncated


async def test_a_tool_call_is_executed_and_fed_back() -> None:
    provider = ScriptedProvider(
        _asks("find_learners", {}),
        _text("You have one learner in scope."),
    )

    outcome = await run_tool_loop(
        provider=provider, request=_request(), execute=_executor(_context())
    )

    assert outcome.tool_names == ("find_learners",)
    assert outcome.text == "You have one learner in scope."
    # Second call carries the assistant turn plus the tool result.
    replay = provider.requests[1].history
    assert replay[0]["role"] == "assistant"
    assert replay[1]["content"][0]["type"] == "tool_result"


async def test_tool_results_are_json_data_not_instructions() -> None:
    provider = ScriptedProvider(_asks("find_learners", {}), _text("Done."))

    await run_tool_loop(provider=provider, request=_request(), execute=_executor(_context()))

    payload = provider.requests[1].history[1]["content"][0]["content"]
    assert json.loads(payload)["total"] == 1


async def test_several_tool_calls_run_in_sequence() -> None:
    provider = ScriptedProvider(
        _asks("list_classes", {}),
        _asks("find_learners", {}),
        _text("Here is the picture."),
    )

    outcome = await run_tool_loop(
        provider=provider, request=_request(), execute=_executor(_context())
    )

    assert outcome.tool_names == ("list_classes", "find_learners")
    assert outcome.iterations == 3


async def test_a_refused_lookup_still_reaches_the_model() -> None:
    """The model must be able to say it cannot see something."""
    provider = ScriptedProvider(
        _asks("get_learner_overview", {"learner": AiPrivacyGuard.pseudonym(OUTSIDER)}),
        _text("I cannot see that learner."),
    )

    outcome = await run_tool_loop(
        provider=provider, request=_request(), execute=_executor(_context())
    )

    payload = json.loads(provider.requests[1].history[1]["content"][0]["content"])
    assert payload["error"] == "not_permitted"
    assert outcome.text == "I cannot see that learner."


async def test_a_model_that_only_ever_asks_for_tools_is_capped() -> None:
    """Otherwise a loop against a paid model runs until the bill notices."""
    provider = ScriptedProvider(*[_asks("find_learners", {}) for _ in range(20)])

    outcome = await run_tool_loop(
        provider=provider,
        request=_request(),
        execute=_executor(_context()),
        max_iterations=3,
    )

    assert outcome.truncated
    assert outcome.iterations == 3
    # One extra call, made without tools, so the user still gets an answer.
    assert provider.requests[-1].tools == ()


async def test_the_total_tool_call_budget_is_enforced() -> None:
    provider = ScriptedProvider(*[_asks("find_learners", {}) for _ in range(20)])

    outcome = await run_tool_loop(
        provider=provider,
        request=_request(),
        execute=_executor(_context()),
        max_iterations=10,
        max_tool_calls=2,
    )

    assert outcome.truncated
    assert len(outcome.tool_names) <= 2


async def test_an_unknown_tool_does_not_break_the_loop() -> None:
    provider = ScriptedProvider(_asks("delete_everything", {}), _text("I cannot do that."))

    outcome = await run_tool_loop(
        provider=provider, request=_request(), execute=_executor(_context())
    )

    payload = json.loads(provider.requests[1].history[1]["content"][0]["content"])
    assert payload["error"] == "unknown_tool"
    assert outcome.text == "I cannot do that."


async def test_tools_are_offered_on_the_first_call() -> None:
    provider = ScriptedProvider(_text("Fine."))

    await run_tool_loop(provider=provider, request=_request(), execute=_executor(_context()))

    assert {item["name"] for item in provider.requests[0].tools} == {
        item["name"] for item in TOOL_SCHEMAS
    }
