"""
Hive Agent
Agentic loop with streaming support.
Tool-calling rounds use non-streaming (fast, short responses).
Final text response streams tokens in real-time to the terminal.
"""

import json
import time
import httpx
import re
from dataclasses import dataclass, field
from typing import Optional, Callable, List

from coordinator.tools import TOOLS, execute_tool
from coordinator.rpc_client import get_inference_base

SYSTEM_PROMPT = """You are Hive, a local AI coding assistant running directly on the user's machine.
You have direct access to their filesystem and terminal through tools.

RULES:
- ALWAYS read files before editing them so you understand the full context.
- Use edit_file for targeted changes. Only use write_file for new files or full rewrites.
- Run commands when the user asks to install, build, test, or run something.
- Be CONCISE. Short answers for simple questions. No bullet-point essays unless asked.
- When you make changes, briefly summarize what changed and why.
- If a task requires multiple steps, do them all autonomously.
- When showing code snippets, use markdown fenced code blocks with the language.
- Do NOT over-explain your capabilities unless specifically asked.

CURRENT WORKING DIRECTORY: {cwd}
OS: {os}
PROJECT CONTEXT: {context}
"""


@dataclass
class ChatResult:
    content: str = ""
    tool_calls_made: int = 0
    tools_used: List[str] = field(default_factory=list)
    total_time: float = 0.0
    eval_count: int = 0
    eval_duration_ns: int = 0
    prompt_eval_count: int = 0
    load_duration_ns: int = 0

    @property
    def tokens_per_sec(self) -> float:
        if self.eval_duration_ns > 0:
            return self.eval_count / (self.eval_duration_ns / 1e9)
        elif self.total_time > 0 and self.eval_count > 0:
            return self.eval_count / self.total_time
        return 0.0

    @property
    def load_time_s(self) -> float:
        return self.load_duration_ns / 1e9 if self.load_duration_ns else 0.0


class HiveAgent:
    def __init__(self, model: str, cwd: str, os_name: str = "Windows", context: str = ""):
        self.model = model
        self.cwd = cwd
        self.os_name = os_name
        self.context = context
        self.messages = []
        self.system_msg = SYSTEM_PROMPT.format(cwd=cwd, os=os_name, context=context or "N/A")
        self.max_tool_rounds = 20
        self.total_tokens_session = 0
        self.total_tool_calls_session = 0
        self.total_messages = 0

    async def chat(
        self,
        user_input: str,
        on_tool_start: Optional[Callable] = None,
        on_tool_end: Optional[Callable] = None,
        on_token: Optional[Callable] = None,
    ) -> ChatResult:
        self.messages.append({"role": "user", "content": user_input})
        self.total_messages += 1

        result = ChatResult()
        start_time = time.time()

        for _round in range(self.max_tool_rounds):
            full_messages = [{"role": "system", "content": self.system_msg}] + self.messages
            if on_token:
                # Streaming mode: stream tokens and detect tool calls
                response_data, streamed_content = await self._call_inference_stream(on_token, full_messages)
            else:
                response_data = await self._call_inference(full_messages)
                streamed_content = None

            response_msg = response_data.get("message", {})

            # Accumulate stats
            if "usage" in response_data:
                result.eval_count += response_data["usage"].get("completion_tokens", 0)
                result.prompt_eval_count += response_data["usage"].get("prompt_tokens", 0)
            else:
                result.eval_count += response_data.get("eval_count", 0)
                result.eval_duration_ns += response_data.get("eval_duration", 0)
                result.prompt_eval_count += response_data.get("prompt_eval_count", 0)
                if response_data.get("load_duration"):
                    result.load_duration_ns += response_data["load_duration"]

            tool_calls = response_msg.get("tool_calls")
            if not tool_calls:
                content = response_msg.get("content", "")
                tool_calls = self._parse_embedded_tool_calls(content)

            if not tool_calls:
                # Final text response
                if streamed_content is not None:
                    content = streamed_content
                else:
                    content = response_msg.get("content", "")
                content = self._strip_think_tags(content)
                self.messages.append({"role": "assistant", "content": content})
                result.content = content
                break

            # Tool calls found — process them
            self.messages.append({
                "role": "assistant",
                "content": response_msg.get("content", ""),
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "unknown")
                tool_args = func.get("arguments", {})
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_args = {}

                result.tool_calls_made += 1
                result.tools_used.append(tool_name)
                self.total_tool_calls_session += 1

                if on_tool_start:
                    on_tool_start(tool_name, tool_args)

                tool_result = execute_tool(tool_name, tool_args, self.cwd)

                if on_tool_end:
                    on_tool_end(tool_name, tool_result)

                tool_id = tc.get("id") or f"call_{tool_name}"
                self.messages.append({
                    "role": "tool", 
                    "content": str(tool_result),
                    "tool_call_id": tool_id,
                    "name": tool_name
                })

        result.total_time = time.time() - start_time
        self.total_tokens_session += result.eval_count
        self.total_messages += 1
        return result

    async def _call_inference(self, full_messages: list) -> dict:
        """Non-streaming OpenAI-compatible call."""
        payload = {
            "model": self.model,
            "messages": full_messages,
            "tools": TOOLS,
            "stream": False,
            "temperature": 0.3,
            "max_tokens": 8192
        }

        base_url = get_inference_base()
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=120.0)
            r.raise_for_status()
            data = r.json()
            return {
                "message": data["choices"][0]["message"],
                "usage": data.get("usage", {})
            }

    async def _call_inference_stream(self, on_token: Callable, full_messages: list) -> tuple:
        """Streaming OpenAI-compatible call with chunked tool call assembly."""
        payload = {
            "model": self.model,
            "messages": full_messages,
            "tools": TOOLS,
            "stream": True,
            "temperature": 0.3,
            "max_tokens": 8192
        }

        content_buffer = ""
        tool_calls_acc = []
        base_url = get_inference_base()

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", f"{base_url}/v1/chat/completions", json=payload, timeout=120.0
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    # Accumulate chunked tool calls
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            while len(tool_calls_acc) <= idx:
                                tool_calls_acc.append({
                                    "id": "", "type": "function", 
                                    "function": {"name": "", "arguments": ""}
                                })
                            if tc.get("id"): 
                                tool_calls_acc[idx]["id"] = tc["id"]
                            fn = tc.get("function", {})
                            if fn.get("name"): 
                                tool_calls_acc[idx]["function"]["name"] += fn["name"]
                            if fn.get("arguments"): 
                                tool_calls_acc[idx]["function"]["arguments"] += fn["arguments"]

                    # Stream text content
                    token = delta.get("content", "")
                    if token:
                        if "<think>" in content_buffer + token:
                            content_buffer += token
                            continue
                        if content_buffer and "</think>" in content_buffer + token:
                            content_buffer += token
                            idx = content_buffer.find("</think>")
                            if idx >= 0:
                                after = content_buffer[idx + 8:]
                                content_buffer = after
                                if after:
                                    on_token(after)
                            continue

                        content_buffer += token
                        on_token(token)

        if tool_calls_acc:
            return {"message": {"role": "assistant", "content": content_buffer, "tool_calls": tool_calls_acc}}, None
        else:
            return {"message": {"role": "assistant", "content": content_buffer}}, content_buffer

    def _strip_think_tags(self, text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _parse_embedded_tool_calls(self, content: str) -> list:
        if not content:
            return []
        pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
        matches = re.findall(pattern, content, re.DOTALL)
        calls = []
        for match in matches:
            try:
                parsed = json.loads(match)
                calls.append({"function": {"name": parsed.get("name", ""), "arguments": parsed.get("arguments", {})}})
            except json.JSONDecodeError:
                continue
        return calls

    def clear_history(self):
        self.messages = []

    def set_cwd(self, cwd: str):
        self.cwd = cwd
        self.system_msg = SYSTEM_PROMPT.format(cwd=cwd, os=self.os_name, context=self.context)

    def get_session_stats(self) -> dict:
        return {
            "messages": self.total_messages,
            "tool_calls": self.total_tool_calls_session,
            "tokens": self.total_tokens_session,
        }
