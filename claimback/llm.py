"""One place that talks to Claude. Every agent call goes through `call()`, which
validates the structured output, logs usage, and turns bad stop reasons into
AgentError so the orchestrator can retry."""
import os

import anthropic
from pydantic import BaseModel

from .log import emit


def _load_dotenv() -> None:
    """Read KEY=value lines from the repo's .env (gitignored) without overriding the real env."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        key, sep, value = line.strip().partition("=")
        if sep and key and value.strip() and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_dotenv()

MODEL = os.environ.get("CLAIMBACK_MODEL", "claude-opus-5-5")
MOCK = os.environ.get("CLAIMBACK_MOCK") == "1"

_client: anthropic.Anthropic | None = None


class AgentError(Exception):
    """A recoverable agent failure (bad output, refusal, truncation, API error)."""


class FatalError(Exception):
    """A failure retrying can't fix (bad key, missing workspace, invalid request)."""


NON_RETRYABLE = (anthropic.BadRequestError, anthropic.AuthenticationError,
                 anthropic.PermissionDeniedError, anthropic.NotFoundError)


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        headers = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):  # for keys not scoped to a workspace
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        _client = anthropic.Anthropic(max_retries=3, default_headers=headers)
    return _client


def call(agent: str, system: str, user: str | list, schema: type[BaseModel],
         effort: str = "medium", max_tokens: int = 16000) -> BaseModel:
    if MOCK:
        from . import mock
        return mock.respond(agent, schema)

    content = user if isinstance(user, list) else [{"type": "text", "text": user}]
    try:
        resp = client().beta.messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        raise AgentError(f"{type(e).__name__}: {e}") from e
    except NON_RETRYABLE as e:
        raise FatalError(f"API {e.status_code}: {_msg(e)}") from e
    except anthropic.APIStatusError as e:
        raise AgentError(f"API {e.status_code}: {_msg(e)}") from e

    _log_usage(agent, resp)
    if resp.stop_reason == "refusal":
        raise AgentError(f"model declined: {getattr(resp.stop_details, 'category', None)}")
    if resp.stop_reason == "max_tokens":
        raise AgentError("output truncated at max_tokens")
    if resp.parsed_output is None:
        raise AgentError("no structured output returned")
    return resp.parsed_output


def research(agent: str, system: str, user: str, allowed_domains: list[str]) -> str:
    """Free-text research turn with Anthropic's server-side web search."""
    if MOCK:
        from . import mock
        return mock.research(agent)

    messages = [{"role": "user", "content": user}]
    tools = [{
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 6,
        "allowed_domains": allowed_domains,
    }]
    try:
        for _ in range(4):  # resume server-tool turns that pause
            resp = client().beta.messages.create(
                model=MODEL, max_tokens=16000, system=system, messages=messages,
                tools=tools, output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            _log_usage(agent, resp)
            for block in resp.content:
                if block.type == "server_tool_use" and block.name == "web_search":
                    emit(agent, "info", f"web search: {block.input.get('query')}")
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
    except NON_RETRYABLE as e:
        raise FatalError(f"API {e.status_code}: {_msg(e)}") from e
    except anthropic.APIStatusError as e:
        raise AgentError(f"API {e.status_code}: {_msg(e)}") from e
    except anthropic.APIConnectionError as e:
        raise AgentError(f"connection: {e}") from e

    if resp.stop_reason == "refusal":
        raise AgentError("model declined research request")
    for block in resp.content:
        if block.type == "web_search_tool_result" and not isinstance(block.content, list):
            raise AgentError(f"web search failed: {getattr(block.content, 'error_code', block.content)}")
    text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise AgentError("research returned no text")
    return text


def _msg(e: anthropic.APIStatusError) -> str:
    try:
        return e.body["error"]["message"]
    except (TypeError, KeyError):
        return e.message


def _log_usage(agent: str, resp) -> None:
    u = resp.usage
    emit(agent, "info", f"{resp.model} · {u.input_tokens} in / {u.output_tokens} out tokens",
         input_tokens=u.input_tokens, output_tokens=u.output_tokens)
