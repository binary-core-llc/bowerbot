# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Test LLM connectivity through litellm for both providers."""

import asyncio
import os


async def test_openai():
    """Test 1: OpenAI responds through litellm."""
    import litellm

    response = await litellm.acompletion(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
        max_tokens=10,
    )

    text = response.choices[0].message.content.strip().lower()
    assert "hello" in text, f"Unexpected response: {text}"
    print(f"✅ test_openai PASSED — response: {text}")


async def test_anthropic():
    """Test 2: Anthropic responds through litellm."""
    import litellm

    response = await litellm.acompletion(
        model="anthropic/claude-sonnet-4-6",
        messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
        max_tokens=10,
    )

    text = response.choices[0].message.content.strip().lower()
    assert "hello" in text, f"Unexpected response: {text}"
    print(f"✅ test_anthropic PASSED — response: {text}")


async def test_tool_calling():
    """Test 3: LLM can call tools (this is how the agent works)."""
    import litellm

    tools = [
        {
            "type": "function",
            "function": {
                "name": "local__search_assets",
                "description": "Search local directories for 3D assets by keyword.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search keyword to match against filenames.",
                        },
                    },
                    "required": ["query"],
                },
            },
        }
    ]

    response = await litellm.acompletion(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You assemble 3D scenes. Use tools to find assets."},
            {"role": "user", "content": "Find me a wooden table."},
        ],
        tools=tools,
        max_tokens=100,
    )

    message = response.choices[0].message

    # LLM should have called the search tool
    assert message.tool_calls is not None, "LLM did not call any tools"
    assert len(message.tool_calls) > 0, "Empty tool_calls list"

    call = message.tool_calls[0]
    assert call.function.name == "local__search_assets"

    import json
    args = json.loads(call.function.arguments)
    assert "query" in args, f"Missing 'query' in args: {args}"

    print(f"✅ test_tool_calling PASSED")
    print(f"   Tool called: {call.function.name}")
    print(f"   Arguments: {args}")


async def main():
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if openai_key:
        await test_openai()
    else:
        print("⏭️  Skipping OpenAI — no OPENAI_API_KEY in .env")

    if anthropic_key:
        await test_anthropic()
    else:
        print("⏭️  Skipping Anthropic — no ANTHROPIC_API_KEY in .env")

    if openai_key:
        await test_tool_calling()
    elif anthropic_key:
        print("⏭️  Skipping tool calling test (needs OpenAI for this test)")
    else:
        print("⏭️  Skipping tool calling — no API keys")

    print("\n🎉 LLM connectivity tests done!")


if __name__ == "__main__":
    asyncio.run(main())