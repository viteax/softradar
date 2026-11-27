from app.llm_openai import OpenAIChat


def test_history_conversion():
    hist = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {
            "role": "assistant",
            "content": "",
            "function_call": {"name": "search_catalog", "arguments": {"query": "x"}},
        },
        {"role": "function", "name": "search_catalog", "content": "[]"},
    ]
    out = OpenAIChat.to_openai(hist)
    assert out[2]["tool_calls"][0]["function"] == {"name": "search_catalog", "arguments": '{"query": "x"}'}
    assert out[3] == {"role": "tool", "tool_call_id": out[2]["tool_calls"][0]["id"], "content": "[]"}
