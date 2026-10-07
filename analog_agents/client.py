import json
import time
from openai import OpenAI

class LocalClient:
    def __init__(self, config):
        self.config = config
        self.calls = []
        self.api = OpenAI(base_url=f"http://127.0.0.1:{config['port']}/v1",
                          api_key="local-only", timeout=config["timeout_seconds"], max_retries=0)

    def ask(self, prompt, payload, schema, agent_name="test"):
        started = time.perf_counter()
        record = {"agent": agent_name, "status": "failed", "usage": None}
        self.calls.append(record)
        try:
            return self._ask(prompt, payload, schema, record)
        except Exception as exc:
            record["error"] = str(exc)
            raise
        finally:
            record["seconds"] = round(time.perf_counter() - started, 4)

    def _ask(self, prompt, payload, schema, record):
        messages = [{"role": "system", "content": prompt + "\nReturn only a JSON object conforming to this schema: " + json.dumps(schema)},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        from transformers import AutoTokenizer
        from .config import project_path
        if not hasattr(self, 'tokenizer'):
            self.tokenizer = AutoTokenizer.from_pretrained(project_path(self.config['model_dir']), local_files_only=True)
        prompt_ids = self.tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
        record['input_tokens_checked'] = len(prompt_ids)
        if len(prompt_ids) + self.config['max_tokens'] > self.config['context_length']:
            raise ValueError('Full experiment input exceeds configured context window; no log/history was truncated')
        response = self.api.chat.completions.create(
            model=self.config["served_model"],
            messages=messages,
            temperature=self.config["temperature"], max_tokens=self.config["max_tokens"],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}, "guided_json": schema})
        choice = response.choices[0]
        if response.usage is not None:
            record["usage"] = {"prompt_tokens": response.usage.prompt_tokens,
                               "completion_tokens": response.usage.completion_tokens,
                               "total_tokens": response.usage.total_tokens}
        else:
            from transformers import AutoTokenizer
            from .config import project_path
            tokenizer = AutoTokenizer.from_pretrained(project_path(self.config['model_dir']), local_files_only=True)
            prompt_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
            output_ids = tokenizer.encode(choice.message.content or '', add_special_tokens=False)
            record['usage'] = {'prompt_tokens':len(prompt_ids), 'completion_tokens':len(output_ids),
                               'total_tokens':len(prompt_ids)+len(output_ids)}
            record['usage_source'] = 'local model tokenizer; output EOS accounting may differ from server'
        record['raw_response'] = choice.message.content
        if choice.finish_reason != "stop":
            raise ValueError(f"Incomplete model output: {choice.finish_reason}")
        result = json.loads(choice.message.content)
        from jsonschema import validate
        validate(result, schema)
        record["status"] = "passed"
        return result


def find_claude():
    """CLAUDE_BIN, then PATH, then the newest VSCode-extension native binary."""
    import glob, os, shutil
    for c in (os.environ.get("CLAUDE_BIN"), os.environ.get("CLAUDE_CODE_EXECPATH"), shutil.which("claude")):
        if c and os.path.exists(c):
            return c
    found = sorted(glob.glob(os.path.expanduser("~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude")))
    if found:
        return found[-1]
    raise RuntimeError("claude CLI not found; set CLAUDE_BIN=/path/to/claude")


class ClaudeCliClient(LocalClient):
    """Drop-in replacement that asks Claude through the `claude -p` CLI (used when no GPU is idle)."""

    def __init__(self, config, model="sonnet"):
        self.config = config
        self.calls = []
        self.model = model

    def _ask(self, prompt, payload, schema, record):
        import os, subprocess
        from jsonschema import validate
        system = prompt + "\nReturn only a JSON object conforming to the supplied JSON schema."
        proc = subprocess.run(
            [find_claude(), "-p", "--model", self.model, "--tools", "",
             "--output-format", "json", "--json-schema", json.dumps(schema),
             "--system-prompt", system],
            input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
            timeout=600)
        if proc.returncode:
            raise RuntimeError(f"claude CLI failed: {proc.stderr[-500:]}")
        out = json.loads(proc.stdout)
        u = out.get("usage") or {}
        pt = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        record["usage"] = {"prompt_tokens": pt, "completion_tokens": u.get("output_tokens", 0),
                           "total_tokens": pt + u.get("output_tokens", 0)}
        record["raw_response"] = out.get("structured_output") or out.get("result")
        result = out.get("structured_output")
        if result is None:
            result = json.loads(out["result"])
        validate(result, schema)
        record["status"] = "passed"
        return result
