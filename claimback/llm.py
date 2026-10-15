"""One place that talks to Claude. Every agent call goes through `call()`, which
validates the structured output, logs usage, and turns bad stop reasons into
AgentError so the orchestrator can retry."""
import os
import time

import anthropic
from pydantic import BaseModel, ValidationError

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

# USD per million tokens: (input, output, cache read). Cache writes bill at 1.25x input.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
WEB_SEARCH_USD = 0.01  # per search ($10 per 1,000)


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
    content = user if isinstance(user, list) else [{"type": "text", "text": user}]
    info = {"schema": schema.__name__, "effort": effort, "max_tokens": max_tokens,
            "prompt_chars": len(system) + sum(len(b.get("text", "")) for b in content)}
    t0 = time.monotonic()
    if MOCK:
        from . import mock
        out = mock.respond(agent, schema, user if isinstance(user, str) else "")
        _log_mock(agent, t0, **info)
        return out

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
            timeout=900 if max_tokens > 16000 else anthropic.NOT_GIVEN,
        )
    except ValidationError as e:
        # The SDK parses before we can check stop_reason; truncated or malformed JSON lands here
        _log_failure(agent, t0, e, **info)
        raise AgentError(f"structured output was cut off or invalid ({e.error_count()} error(s))") from e
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        _log_failure(agent, t0, e, **info)
        raise AgentError(f"{type(e).__name__}: {e}") from e
    except NON_RETRYABLE as e:
        _log_failure(agent, t0, e, **info)
        raise FatalError(f"API {e.status_code}: {_msg(e)}") from e
    except anthropic.APIStatusError as e:
        _log_failure(agent, t0, e, **info)
        raise AgentError(f"API {e.status_code}: {_msg(e)}") from e

    _log_usage(agent, resp, t0, **info)
    if resp.stop_reason == "refusal":
        raise AgentError(f"model declined: {getattr(resp.stop_details, 'category', None)}")
    if resp.stop_reason == "max_tokens":
        raise AgentError("output truncated at max_tokens")
    if resp.parsed_output is None:
        raise AgentError("no structured output returned")
    return resp.parsed_output


def research(agent: str, system: str, user: str, allowed_domains: list[str]) -> str:
    """Free-text research turn with Anthropic's server-side web search."""
    info = {"schema": "research notes (web search)", "effort": "medium", "max_tokens": 16000,
            "prompt_chars": len(system) + len(user)}
    if MOCK:
        from . import mock
        t0 = time.monotonic()
        out = mock.research(agent)
        _log_mock(agent, t0, **info)
        return out

    messages = [{"role": "user", "content": user}]
    tools = [{
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 6,
        "allowed_domains": allowed_domains,
    }]
    emit(agent, "info", f"web research: up to 6 searches, limited to {len(allowed_domains)} independent "
                        "domains (government, journals, professional societies)",
         type="web_research", allowed_domains=allowed_domains, max_searches=6)
    try:
        for turn in range(1, 5):  # resume server-tool turns that pause
            t0 = time.monotonic()
            resp = client().beta.messages.create(
                model=MODEL, max_tokens=16000, system=system, messages=messages,
                tools=tools, output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            _log_usage(agent, resp, t0, turn=turn, **info)
            for block in resp.content:
                if block.type == "server_tool_use" and block.name == "web_search":
                    emit(agent, "info", f"web search: {block.input.get('query')}", type="web_search",
                         query=block.input.get("query"))
                elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                    hits = [{"title": getattr(r, "title", ""), "url": getattr(r, "url", "")} for r in block.content]
                    emit(agent, "info", f"web search returned {len(hits)} pages"
                         + (": " + ", ".join(dict.fromkeys(_host(h["url"]) for h in hits)) if hits else ""),
                         type="web_search_results", results=hits)
            if resp.stop_reason != "pause_turn":
                break
            emit(agent, "info", "web search paused the turn; resuming it", type="pause_turn", turn=turn)
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
    emit(agent, "info", f"research notes: {len(text.split()):,} words handed to the structuring step",
         type="research_notes", words=len(text.split()))
    return text


def _msg(e: anthropic.APIStatusError) -> str:
    try:
        return e.body["error"]["message"]
    except (TypeError, KeyError):
        return e.message


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0,
             searches: int = 0) -> float:
    """Estimated list-price cost of one call."""
    price = next((v for k, v in sorted(PRICES.items(), key=lambda kv: -len(kv[0])) if model.startswith(k)),
                 PRICES["claude-opus-5-5"])
    p_in, p_out, p_read = price
    return round((input_tokens * p_in + output_tokens * p_out + cache_read * p_read
                  + cache_write * p_in * 1.25) / 1e6 + searches * WEB_SEARCH_USD, 5)


def _log_usage(agent: str, resp, t0: float, **info) -> None:
    """One line per model call: which model at what effort, how long, how many tokens, what it cost."""
    u = resp.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
    duration = round(time.monotonic() - t0, 2)
    cost = cost_usd(resp.model, u.input_tokens, u.output_tokens, cache_read, cache_write, searches)
    extra = f" · {searches} web searches" if searches else ""
    emit(agent, "info", f"model call · {resp.model} · effort {info.get('effort')} · {u.input_tokens:,} in / "
                        f"{u.output_tokens:,} out tokens{extra} · {duration:.1f}s · ${cost:.4f}",
         type="model_call", model=resp.model, requested_model=MODEL, fallback_used=resp.model != MODEL,
         input_tokens=u.input_tokens, output_tokens=u.output_tokens, cache_read_input_tokens=cache_read,
         cache_creation_input_tokens=cache_write, web_search_requests=searches, duration_s=duration,
         cost_usd=cost, stop_reason=resp.stop_reason, **info)


def _log_failure(agent: str, t0: float, e: Exception, **info) -> None:
    duration = round(time.monotonic() - t0, 2)
    emit(agent, "warn", f"model call failed after {duration:.1f}s: {type(e).__name__}",
         type="model_call_failed", model=MODEL, duration_s=duration, error=type(e).__name__, **info)


def _log_mock(agent: str, t0: float, **info) -> None:
    emit(agent, "info", f"model call · mock (no API call) · {info.get('schema')}", type="model_call",
         model="mock", mock=True, input_tokens=0, output_tokens=0, cost_usd=0.0,
         duration_s=round(time.monotonic() - t0, 2), **info)
