"""Provider-selection test (no API calls — construction only).

The grading box may supply OPENAI_API_KEY and/or ANTHROPIC_API_KEY. We must
prefer Anthropic, fall back to OpenAI, and run retrieval-only with no key.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from coder.rerank import make_reranker  # noqa: E402


def _select(**env):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(k, None)
    os.environ.update(env)
    r = make_reranker()
    return r.backend.name if r else None


def test_provider_selection():
    assert _select() is None
    assert _select(ANTHROPIC_API_KEY="x") == "anthropic"
    assert _select(OPENAI_API_KEY="x") == "openai"
    assert _select(ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x") == "anthropic"
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(k, None)


if __name__ == "__main__":
    test_provider_selection()
    print("provider selection test passed")
