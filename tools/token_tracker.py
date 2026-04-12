"""Token Tracker — per-agent OpenAI token usage logging and budget estimation."""

from __future__ import annotations

import tiktoken

_ledger: dict[str, list[dict]] = {}


def track_call(agent_name: str, response) -> None:
    """Record token usage from an OpenAI chat completion response.

    Args:
        agent_name: Identifier for the calling agent (e.g. "researcher", "methodology").
        response: The ChatCompletion object returned by client.chat.completions.create().
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    entry = {
        "prompt_tokens": usage.prompt_tokens or 0,
        "completion_tokens": usage.completion_tokens or 0,
        "total_tokens": usage.total_tokens or 0,
    }
    _ledger.setdefault(agent_name, []).append(entry)


def estimate_tokens(text: str, model: str = "gpt-4o") -> int:
    """Estimate token count for a string using tiktoken.

    Falls back to cl100k_base encoding if the model is not recognized.
    """
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def print_summary() -> None:
    """Print a per-agent token usage summary to stdout."""
    if not _ledger:
        print("[token_tracker] No OpenAI calls recorded.")
        return

    print("\n" + "=" * 64)
    print("TOKEN USAGE SUMMARY")
    print("=" * 64)
    print(f"{'Agent':<20} {'Calls':>6} {'Prompt':>10} {'Completion':>10} {'Total':>10}")
    print("-" * 64)

    grand_prompt = 0
    grand_completion = 0
    grand_total = 0

    for agent_name, entries in sorted(_ledger.items()):
        p = sum(e["prompt_tokens"] for e in entries)
        c = sum(e["completion_tokens"] for e in entries)
        t = sum(e["total_tokens"] for e in entries)
        grand_prompt += p
        grand_completion += c
        grand_total += t
        print(f"{agent_name:<20} {len(entries):>6} {p:>10,} {c:>10,} {t:>10,}")

    print("-" * 64)
    total_calls = sum(len(v) for v in _ledger.values())
    print(f"{'TOTAL':<20} {total_calls:>6} {grand_prompt:>10,} {grand_completion:>10,} {grand_total:>10,}")
    print("=" * 64 + "\n")


def reset() -> None:
    """Clear the ledger (useful for testing)."""
    _ledger.clear()
