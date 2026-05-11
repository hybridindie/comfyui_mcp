"""MCP eval harness that runs questions against an Ollama-served model.

Mirrors the structure of `mcp-builder`'s `scripts/evaluation.py` but uses Ollama's
OpenAI-style tool-use API instead of Anthropic. Useful when you want to test the
MCP server's tool descriptions/schemas against open-weight or Ollama-cloud models.

Usage:

    uv run --with ollama --with mcp python scripts/run_eval_ollama.py \\
        --model gpt-oss:120b-cloud \\
        --eval evals/2026-05-11-comfyui-mcp-v1.xml \\
        --output evals/2026-05-11-report.md \\
        -c .venv/bin/python -a -m comfyui_mcp.server \\
        -e COMFYUI_URL=http://localhost:8188

Requires:
- Ollama daemon running locally (`ollama serve`).
- For *-cloud models: be signed in (`ollama signin` if needed) so the daemon can
  proxy cloud inference.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shlex
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from ollama import AsyncClient as OllamaAsyncClient

EVALUATION_PROMPT = """You are an AI assistant with access to tools.

When given a task, you MUST:
1. Use the available tools to complete the task
2. Provide summary of each step in your approach, wrapped in <summary> tags
3. Provide feedback on the tools provided, wrapped in <feedback> tags
4. Provide your final response, wrapped in <response> tags

Summary Requirements:
- In your <summary> tags, you must explain:
  - The steps you took to complete the task
  - Which tools you used, in what order, and why
  - The inputs you provided to each tool
  - The outputs you received from each tool
  - A summary for how you arrived at the response

Feedback Requirements:
- In your <feedback> tags, provide constructive feedback on the tools:
  - Comment on tool names: Are they clear and descriptive?
  - Comment on input parameters: Are they well-documented?
    Are required vs optional parameters clear?
  - Comment on descriptions: Do they accurately describe what the tool does?
  - Comment on any errors encountered during tool usage.
  - Identify specific areas for improvement and explain WHY they would help.
  - Be specific and actionable in your suggestions.

Response Requirements:
- Your response should be concise and directly address what was asked.
- Always wrap your final response in <response> tags.
- If you cannot solve the task return <response>NOT_FOUND</response>.
- For numeric responses, provide just the number.
- For names or text, provide the exact text requested.
- Your response should go last."""


def parse_evaluation_file(path: Path) -> list[dict[str, str]]:
    # S314 rationale: this script only ever reads eval XML files we author and
    # commit ourselves; there is no untrusted-input attack surface here.
    tree = ET.parse(path)  # noqa: S314
    root = tree.getroot()
    out: list[dict[str, str]] = []
    for qa in root.findall(".//qa_pair"):
        q = qa.find("question")
        a = qa.find("answer")
        if q is not None and a is not None:
            out.append({"question": (q.text or "").strip(), "answer": (a.text or "").strip()})
    return out


def extract_xml_content(text: str | None, tag: str) -> str | None:
    if not text:
        return None
    matches = re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return matches[-1].strip() if matches else None


_MD_STRIPPER = re.compile(r"^[\s>*_`#\-]+|[\s>*_`#\-]+$")


def extract_response_with_fallback(text: str | None) -> str | None:
    """Return the <response> contents if present, else the last meaningful line.

    Many OSS models (e.g. gpt-oss-cloud) don't reliably emit XML wrappers even
    when the system prompt requires them. As a defense, we fall back to the
    last non-empty line of the assistant text, stripped of trailing/leading
    markdown decoration (bold, blockquote, bullets, backticks, headers, etc.).
    """
    primary = extract_xml_content(text, "response")
    if primary is not None:
        return primary
    if not text:
        return None
    lines = [_MD_STRIPPER.sub("", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return lines[-1] if lines else None


def mcp_tools_to_ollama(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP `inputSchema` tool defs to Ollama/OpenAI function-tool defs."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": (t.get("description") or "")[:1024],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


async def call_tool_safely(session: ClientSession, name: str, args: dict[str, Any]) -> str:
    """Call an MCP tool and return its content as a string."""
    try:
        result = await session.call_tool(name, arguments=args)
        # result.content is a list of TextContent / ImageContent / EmbeddedResource
        chunks: list[str] = []
        for block in result.content or []:
            if hasattr(block, "text"):
                chunks.append(block.text)
            else:
                chunks.append(repr(block))
        return "\n".join(chunks) if chunks else "(empty)"
    except Exception as e:
        return f"Error executing tool {name}: {e}\n{traceback.format_exc()}"


_NUDGE_PROMPT = (
    "Based on the tool results above, provide your final answer now. "
    "It MUST be wrapped in <response>...</response> tags (plus <summary> and "
    "<feedback>) as instructed. Do not call any more tools."
)


async def agent_loop(
    client: OllamaAsyncClient,
    model: str,
    question: str,
    ollama_tools: list[dict[str, Any]],
    session: ClientSession,
    max_iterations: int = 30,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Run an Ollama tool-use agent loop until the model produces a non-tool response."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": EVALUATION_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_metrics: dict[str, dict[str, Any]] = {}
    nudged = False

    for _ in range(max_iterations):
        response = await client.chat(model=model, messages=messages, tools=ollama_tools)
        msg = response["message"]
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        # Preserve the assistant turn (including any tool_calls) for the next round.
        assistant_turn: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_turn["tool_calls"] = tool_calls
        messages.append(assistant_turn)

        if not tool_calls:
            # Final answer turn. Many OSS models terminate after the tool calls
            # with an empty or unwrapped reply. Nudge once asking them to emit
            # the required <response> wrapper, then accept whatever comes back.
            if not nudged and ("<response>" not in content):
                nudged = True
                messages.append({"role": "user", "content": _NUDGE_PROMPT})
                continue
            return content, tool_metrics

        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments") or {}
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)

            t0 = time.time()
            tool_response = await call_tool_safely(session, name, args)
            dt = time.time() - t0

            bucket = tool_metrics.setdefault(name, {"count": 0, "durations": []})
            bucket["count"] += 1
            bucket["durations"].append(dt)

            messages.append({"role": "tool", "name": name, "content": tool_response})

    return "<response>NOT_FOUND</response>  # exhausted max_iterations", tool_metrics


REPORT_HEADER = """# Evaluation Report (Ollama)

- **Model**: `{model}`
- **Accuracy**: {correct}/{total} ({accuracy:.1f}%)
- **Average task duration**: {avg_duration:.2f}s
- **Average tool calls per task**: {avg_tool_calls:.2f}
- **Total tool calls**: {total_tool_calls}

---
"""

TASK_TEMPLATE = """
### Task {n}

**Question**: {question}
**Expected**: `{expected}`
**Actual**: `{actual}`
**Correct**: {mark}
**Duration**: {duration:.2f}s
**Tool calls** ({num_tool_calls}): {tool_calls}

**Summary**

{summary}

**Feedback**

{feedback}

---
"""


def format_report(model: str, results: list[dict[str, Any]]) -> str:
    total = len(results)
    correct = sum(r["score"] for r in results)
    accuracy = (correct / total * 100) if total else 0.0
    avg_duration = (sum(r["duration"] for r in results) / total) if total else 0.0
    total_tool_calls = sum(r["num_tool_calls"] for r in results)
    avg_tool_calls = (total_tool_calls / total) if total else 0.0

    body = [
        REPORT_HEADER.format(
            model=model,
            correct=correct,
            total=total,
            accuracy=accuracy,
            avg_duration=avg_duration,
            avg_tool_calls=avg_tool_calls,
            total_tool_calls=total_tool_calls,
        )
    ]
    for i, r in enumerate(results, start=1):
        tool_summary = (
            ", ".join(f"{name} x{m['count']}" for name, m in r["tool_metrics"].items()) or "-"
        )
        body.append(
            TASK_TEMPLATE.format(
                n=i,
                question=r["question"],
                expected=r["expected"],
                actual=r["actual"] or "(no <response>)",
                mark="✅" if r["score"] else "❌",
                duration=r["duration"],
                num_tool_calls=r["num_tool_calls"],
                tool_calls=tool_summary,
                summary=r["summary"] or "(no summary)",
                feedback=r["feedback"] or "(no feedback)",
            )
        )
    return "\n".join(body)


async def main_async(args: argparse.Namespace) -> int:
    eval_path = Path(args.eval).resolve()
    if not eval_path.exists():
        print(f"❌ Eval file not found: {eval_path}", file=sys.stderr)
        return 2

    qa_pairs = parse_evaluation_file(eval_path)
    print(f"📋 Loaded {len(qa_pairs)} eval tasks from {eval_path}")

    env: dict[str, str] = {}
    for kv in args.env or []:
        if "=" not in kv:
            print(f"⚠️  Skipping malformed --env entry: {kv!r}", file=sys.stderr)
            continue
        k, v = kv.split("=", 1)
        env[k] = v

    ollama = OllamaAsyncClient(host=args.host)

    server_args = shlex.split(args.args) if args.args else []
    print(f"🚀 Launching MCP server: {args.command} {' '.join(server_args)}")
    server_params = StdioServerParameters(command=args.command, args=server_args, env=env or None)

    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        tools_resp = await session.list_tools()
        mcp_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in tools_resp.tools
        ]
        ollama_tools = mcp_tools_to_ollama(mcp_tools)
        print(f"🔧 MCP server exposes {len(ollama_tools)} tools")

        results: list[dict[str, Any]] = []
        for i, qa in enumerate(qa_pairs, start=1):
            print(f"\n[{i}/{len(qa_pairs)}] {qa['question'][:100]}...")
            t0 = time.time()
            try:
                response_text, tool_metrics = await agent_loop(
                    ollama, args.model, qa["question"], ollama_tools, session
                )
            except Exception as e:
                print(f"  ⚠️  Task crashed: {e}")
                response_text = ""
                tool_metrics = {}
            duration = time.time() - t0

            actual = extract_response_with_fallback(response_text)
            summary = extract_xml_content(response_text, "summary")
            feedback = extract_xml_content(response_text, "feedback")
            score = int(actual is not None and actual == qa["answer"])
            num_tool_calls = sum(m["count"] for m in tool_metrics.values())

            mark = "PASS" if score else "FAIL"
            print(
                f"  -> actual={actual!r}  expected={qa['answer']!r}  {mark}  "
                f"({duration:.1f}s, {num_tool_calls} tool calls)"
            )

            results.append(
                {
                    "question": qa["question"],
                    "expected": qa["answer"],
                    "actual": actual,
                    "score": score,
                    "duration": duration,
                    "tool_metrics": tool_metrics,
                    "num_tool_calls": num_tool_calls,
                    "summary": summary,
                    "feedback": feedback,
                }
            )

    report = format_report(args.model, results)
    if args.output:
        Path(args.output).write_text(report)
        print(f"\n📝 Report written to {args.output}")
    else:
        print("\n" + report)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Run MCP eval against an Ollama-served model.")
    p.add_argument("--eval", required=True, help="Path to evaluation XML file")
    p.add_argument("--model", default="gpt-oss:120b-cloud", help="Ollama model to use")
    p.add_argument("--host", default="http://localhost:11434", help="Ollama daemon URL")
    p.add_argument("--output", "-o", help="Output path for the report (default: stdout)")
    p.add_argument("-c", "--command", required=True, help="Command to launch MCP server (stdio)")
    p.add_argument(
        "-a",
        "--args",
        default="",
        help="Args for the MCP server command, as a single shell-quoted string "
        "(e.g. '-m comfyui_mcp.server'). Parsed with shlex.split.",
    )
    p.add_argument("-e", "--env", nargs="+", default=[], help="Env vars in KEY=VALUE form")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
