"""Bounded OpenAI review over a local, read-only evidence interface."""

import base64
import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TERRA = os.getenv("OPENAI_TERRA_MODEL", "gpt-6.1-terra")
SOL = os.getenv("OPENAI_SOL_MODEL", "gpt-6.1-sol")


def tool(name, description, **properties):
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": {
                key: {"type": kind} for key, kind in properties.items()},
                "required": list(properties), "additionalProperties": False}}


TOOLS = [
    tool("read", "Read a slice of a public evidence or reference file. Offset is a character offset.",
         path="string", offset="integer"),
    tool("query", "Run an evidence.py query (list, grep, page, tables, struck, rows). "
         "Supply the subcommand and its arguments as separate strings.", arguments="array"),
    tool("image", "Read a prepared JPEG page such as .data-runs/pages/STEM/2.jpg.", path="string"),
]
TOOLS[1]["parameters"]["properties"]["arguments"]["items"] = {"type": "string"}
# The runner's own validator, offered when it can check the answer: the model never runs commands or
# writes files, so this is how it learns what its JSON still gets wrong before returning it.
CHECK = tool("check", "Check a complete answer, passed as a JSON string, against the runner's validator. "
             "Writes nothing. Returns 'passed' or what is wrong.", answer="string")
CHECK_LIMIT = 3


def checked(check, arguments, count):
    if count > CHECK_LIMIT:
        return ("Check limit reached. Return your final JSON now; if a fact is still unconfirmed, return "
                "status pending with it listed as unresolved.")
    try:
        value = json.loads(json.loads(arguments)["answer"])
    except (ValueError, TypeError, KeyError):
        return "The answer is not a JSON object passed as a string."
    if not isinstance(value, dict):
        return "The answer is not a JSON object."
    try:
        return check(value)[:4000]
    except (OSError, ValueError, TypeError, KeyError) as error:
        return f"Check failed: {error}"[:4000]


def evidence(root, name, args):
    if name == "query":
        arguments = args["arguments"]
        if (not arguments or arguments[0] not in {"list", "grep", "page", "tables", "struck", "rows"}
                or len(arguments) > 12 or any(len(argument) > 500 for argument in arguments)):
            raise ValueError("invalid evidence query")
        result = subprocess.run([sys.executable, "scripts/evidence.py", *arguments], cwd=root,
                                capture_output=True, text=True, timeout=25,
                                env={"PATH": os.environ["PATH"], "PYTHONUTF8": "1"})
        output = result.stdout if result.returncode == 0 else result.stderr
        return output if len(output) <= 8000 else output[:8000] + "\n[Truncated. Narrow the query.]"

    path = (root / args["path"]).resolve()
    relative = path.relative_to(root).parts
    allowed = {".data-runs", ".shadow-evidence", ".arbiter", "schema", "contracts",
               "academic-calendar", "departments", "important-dates", "exam", "exam-week-classes"}
    if not relative or relative[0] not in allowed:
        raise ValueError("path is outside the public evidence and reference directories")
    if name == "image" and relative[:2] == (".data-runs", "pages") and path.suffix == ".jpg":
        if path.stat().st_size > 512_000:
            raise ValueError("page image is too large")
        encoded = base64.b64encode(path.read_bytes()).decode()
        return [{"type": "input_image", "image_url": "data:image/jpeg;base64," + encoded, "detail": "high"}]
    if name != "read" or path.suffix not in {".txt", ".md", ".json", ".jsonl"}:
        raise ValueError("unsupported evidence file type")
    offset = args["offset"]
    if offset < 0 or path.stat().st_size > 32_000_000:
        raise ValueError("invalid offset or evidence file too large")
    content = path.read_text(encoding="utf-8")
    end = min(offset + 8000, len(content))
    return f"[{path.relative_to(root)} characters {offset}–{end} of {len(content)}]\n" + content[offset:end]


def responses(key, payload):
    request = Request("https://api.openai.com/v1/responses", method="POST",
                      data=json.dumps(payload).encode(),
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=300) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"OpenAI Responses API returned HTTP {error.code}") from None


class Review:
    def __init__(self, key):
        self.key = key
        self.tokens = 0
        self.calls = []  # one entry per response, for the run record
        self.limit = int(os.getenv("OPENAI_RUN_TOKEN_LIMIT", "240000"))

    def ask(self, root, model, role, context, effort="low", label=None, check=None):
        """One answer JSON. `check(value)` validates a draft answer and returns what is wrong."""
        messages = [{"role": "developer", "content": role},
                    {"role": "user", "content": context}]
        tools, checks = ([*TOOLS, CHECK] if check else TOOLS), 0
        for _ in range(14):
            if self.tokens >= self.limit:
                raise RuntimeError("model token budget reached")
            result = responses(self.key, {
                "model": model, "input": messages, "tools": tools, "store": False,
                "include": ["reasoning.encrypted_content"], "max_output_tokens": 12000,
                "reasoning": {"effort": effort}, "text": {"format": {"type": "json_object"}},
            })
            usage = result["usage"]
            self.tokens += usage["total_tokens"]
            self.calls.append({"label": label, "model": model, "input": usage["input_tokens"],
                               "cached": usage.get("input_tokens_details", {}).get("cached_tokens", 0),
                               "output": usage["output_tokens"], "total": usage["total_tokens"]})
            print(json.dumps({"model": model, "inputTokens": usage["input_tokens"],
                              "cachedTokens": usage.get("input_tokens_details", {}).get("cached_tokens", 0),
                              "outputTokens": usage["output_tokens"], "runTokens": self.tokens}), flush=True)
            if result["status"] != "completed" or self.tokens > self.limit:
                raise RuntimeError("model did not complete within the response or run token budget")
            output = result["output"]
            calls = [item for item in output if item["type"] == "function_call"]
            if not calls:
                answer = "".join(part["text"] for item in output if item["type"] == "message"
                                 for part in item["content"] if part["type"] == "output_text")
                value = json.loads(answer)
                if not isinstance(value, dict):
                    raise ValueError("expected a JSON object from the reviewer")
                return value
            if len(calls) > 8:
                raise RuntimeError("too many evidence queries in one response")
            messages.extend(output)
            for call in calls:
                if check and call["name"] == "check":
                    checks += 1
                    messages.append({"type": "function_call_output", "call_id": call["call_id"],
                                     "output": checked(check, call["arguments"], checks)})
                    continue
                try:
                    data = evidence(root, call["name"], json.loads(call["arguments"]))
                except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
                    data = f"Evidence query failed ({type(error).__name__}). Check the path or narrow the query."
                messages.append({"type": "function_call_output", "call_id": call["call_id"], "output": data})
        raise RuntimeError("review exceeded the response limit")
