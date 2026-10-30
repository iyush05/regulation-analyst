"""Amazon Bedrock provider against a simulated Converse endpoint; not a live-model test."""

import json

import httpx
import pytest
from pydantic import BaseModel

from regulation_analyst.agent import run_agent
from regulation_analyst.errors import ResearchError
from regulation_analyst.providers import (
    BedrockProvider,
    OpenAIProvider,
    UsageBudget,
    chat_configured,
    chat_provider,
    image_input,
)

MODEL = "us.example.model-v1:0"


def endpoint(replies, requests):
    """Answers each Converse request with the next scripted reply."""
    replies = iter(replies)

    def handler(request):
        requests.append(
            {
                "url": str(request.url),
                "auth": request.headers["authorization"],
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(200, json=next(replies))

    return httpx.Client(transport=httpx.MockTransport(handler))


def tool_reply(name, arguments, *, tokens=30, stop="tool_use"):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": f"t-{name}", "name": name, "input": arguments}}
                ],
            }
        },
        "stopReason": stop,
        "usage": {"inputTokens": tokens - 10, "outputTokens": 10, "totalTokens": tokens},
    }


def test_agent_messages_translate_both_ways():
    requests = []
    client = endpoint([tool_reply("get_table", {"company": "Infosys"})], requests)
    provider = BedrockProvider(model=MODEL, api_key="secret", region="ap-south-1", client=client)
    tools = [
        {
            "type": "function",
            "name": "get_table",
            "description": "Fetch",
            "parameters": {"type": "object"},
        }
    ]
    messages = [
        {"role": "system", "content": "Rules"},
        {"role": "user", "content": "Question"},
        {"type": "function_call", "name": "list_metrics", "call_id": "c1", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": '{"status":"ok"}'},
    ]
    shaped = provider.respond(messages, tools, max_output_tokens=500, timeout=5)
    sent = requests[0]
    assert sent["url"] == (
        "https://bedrock-runtime.ap-south-1.amazonaws.com/model/us.example.model-v1%3A0/converse"
    )
    assert sent["auth"] == "Bearer secret"
    body = sent["body"]
    assert body["system"][0] == {"text": "Rules"}
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][1]["content"][0]["toolUse"] == {
        "toolUseId": "c1",
        "name": "list_metrics",
        "input": {},
    }
    assert body["messages"][2]["content"][0]["toolResult"]["toolUseId"] == "c1"
    # Not forced: current Claude models reject forced tool choice.
    assert body["toolConfig"]["toolChoice"] == {"auto": {}}
    assert body["toolConfig"]["tools"][0]["toolSpec"]["name"] == "get_table"
    assert body["inferenceConfig"] == {"maxTokens": 500}
    assert shaped["output"] == [
        {
            "type": "function_call",
            "name": "get_table",
            "call_id": "t-get_table",
            "arguments": '{"company": "Infosys"}',
        }
    ]
    assert shaped["usage"] == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
    assert shaped["status"] == "completed"


class Answer(BaseModel):
    name: str
    year: int


def test_structured_output_uses_a_forced_tool_and_validates():
    requests = []
    budget = UsageBudget(1000)
    client = endpoint(
        [
            tool_reply("submit", {"name": "Infosys", "year": 2025}),
            tool_reply("submit", {"name": 1}),
        ],
        requests,
    )
    provider = BedrockProvider(model=MODEL, api_key="k", client=client)
    content = [{"type": "input_text", "text": "Read"}, image_input(b"\x89PNG\r\n\x1a\nxyz")]
    assert provider.structured("Do it", content, Answer, budget=budget) == Answer(
        name="Infosys", year=2025
    )
    body = requests[0]["body"]
    assert body["toolConfig"]["toolChoice"] == {"auto": {}}
    assert "submit tool" in body["system"][1]["text"]
    schema = body["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert schema["required"] == ["name", "year"] and schema["additionalProperties"] is False
    assert body["messages"][0]["content"][1]["image"]["format"] == "png"
    assert budget.usage["total_tokens"] == 30
    with pytest.raises(ResearchError, match="did not match"):
        provider.structured("Do it", content, Answer)
    with pytest.raises(ResearchError, match="no web search"):
        provider.structured("Find", content, Answer, web_search=True)


def test_errors_never_echo_the_key():
    def handler(request):
        return httpx.Response(403, text="denied for secret-key")

    provider = BedrockProvider(
        model=MODEL,
        api_key="secret-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ResearchError) as error:
        provider.respond([{"role": "user", "content": "q"}], [], max_output_tokens=10, timeout=1)
    assert "secret-key" not in str(error.value) and "403" in str(error.value)


def test_provider_switch_and_configuration(monkeypatch):
    monkeypatch.setenv("REGULATION_AGENT_MODEL", MODEL)
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "b")
    monkeypatch.delenv("REGULATION_MODEL_PROVIDER", raising=False)
    assert isinstance(chat_provider(), OpenAIProvider)
    monkeypatch.setenv("REGULATION_MODEL_PROVIDER", "bedrock")
    assert isinstance(chat_provider(), BedrockProvider) and chat_configured()
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK")
    assert not chat_configured()
    monkeypatch.setenv("REGULATION_MODEL_PROVIDER", "other")
    with pytest.raises(ResearchError, match="openai or bedrock"):
        chat_provider()


def test_agent_runs_end_to_end_through_bedrock(service, tmp_path):
    requests = []
    finish = {
        "fact_ids": ["infosys-indas-2025-revenue"],
        "calculation_ids": [],
        "passage_ids": [],
        "provision_ids": [],
        "gaps": [],
    }
    client = endpoint(
        [
            tool_reply(
                "get_table", {"company": "Infosys", "years": ["FY25"], "metrics": ["revenue"]}
            ),
            tool_reply("finish", finish),
        ],
        requests,
    )
    provider = BedrockProvider(model=MODEL, api_key="k", client=client)
    answer = run_agent(service, "Infosys revenue FY25", provider, log_dir=tmp_path)
    assert answer.status == "ok", answer.message
    assert "₹1,62,990 cr" in answer.data["answer"]
    second = requests[1]["body"]["messages"]
    assert second[-1]["content"][0]["toolResult"]["toolUseId"] == "t-get_table"
    assert json.loads(open(answer.data["run_log"]).read())["model"] == f"bedrock:{MODEL}"


def test_refusals_explain_the_aws_reason_without_the_key():
    def handler(request):
        return httpx.Response(
            403,
            headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal.amazon.com/"},
            json={"message": "You don't have access to the model with the specified model ID. k-9"},
        )

    provider = BedrockProvider(
        model=MODEL, api_key="k-9", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ResearchError) as error:
        provider.respond([{"role": "user", "content": "q"}], [], max_output_tokens=10, timeout=1)
    message = str(error.value)
    assert "403" in message
    assert "AccessDeniedException: You don't have access to the model" in message
    assert "k-9" not in message
