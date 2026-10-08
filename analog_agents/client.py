import json
import time
from openai import OpenAI
from .rules import with_global_rules
from .context import compact_payload, dumps

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
            prompt, payload = with_global_rules(prompt, payload, record)
            payload = compact_payload(payload, record)
            return self._ask(prompt, payload, schema, record)
        except Exception as exc:
            record["error"] = str(exc)
            raise
        finally:
            record["seconds"] = round(time.perf_counter() - started, 4)

    def _ask(self, prompt, payload, schema, record):
        messages = [{"role": "system", "content": prompt + "\nReturn only a JSON object conforming to this schema: " + dumps(schema)},
                    {"role": "user", "content": dumps(payload)}]
        from transformers import AutoTokenizer
        from .config import project_path
        if not hasattr(self, 'tokenizer'):
            self.tokenizer = AutoTokenizer.from_pretrained(project_path(self.config['model_dir']), local_files_only=True)
        prompt_ids = self.tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
        record['input_tokens_checked'] = len(prompt_ids)
        if len(prompt_ids) + self.config['max_tokens'] > self.config['context_length']:
            raise ValueError(f'Packed experiment input ({len(prompt_ids)} tokens) + output reserve ({self.config["max_tokens"]}) exceeds context window ({self.config["context_length"]}); constraints/current evidence were not silently dropped')
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

    def __init__(self, config, model="claude-sonnet-5-5"):
        self.config = config
        self.calls = []
        self.model = model

    def _ask(self, prompt, payload, schema, record):
        import os, subprocess, tempfile
        from jsonschema import validate
        system = prompt + "\nReturn only a JSON object conforming to the supplied JSON schema."
        # Fresh directory prevents automatic loading of project-local instructions
        # containing archived experiment references. Tools are disabled; no resume.
        with tempfile.TemporaryDirectory(prefix='sizing-input-') as isolated_workdir:
            proc = subprocess.run(
                [find_claude(), "-p", "--model", self.model, "--tools", "",
                 "--output-format", "json", "--json-schema", dumps(schema),
                 "--system-prompt", system],
                input=dumps(payload), capture_output=True, text=True,
                timeout=600, cwd=isolated_workdir)
        try:
            out = json.loads(proc.stdout)
        except ValueError:
            out = {}
        if out.get("is_error"):
            raise RuntimeError(f"claude CLI error ({self.model}): {out.get('result')}")
        if proc.returncode or not out:
            raise RuntimeError(f"claude CLI failed ({self.model}): {(proc.stderr or proc.stdout)[-500:]}")
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


def find_codex():
    """CODEX_BIN, then PATH, then the newest VSCode-extension (openai.chatgpt) codex binary."""
    import glob, os, shutil
    for c in (os.environ.get("CODEX_BIN"), shutil.which("codex")):
        if c and os.path.exists(c):
            return c
    found = sorted(glob.glob(os.path.expanduser("~/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex")))
    if found:
        return found[-1]
    raise RuntimeError("codex CLI not found; set CODEX_BIN=/path/to/codex")


class CodexCliClient(LocalClient):
    """Asks Codex (`codex exec`) using the account already logged in through VS Code (~/.codex/auth.json)."""

    def __init__(self, config, model="gpt-6-astra"):
        self.config = config
        self.calls = []
        self.model = model

    def _ask(self, prompt, payload, schema, record):
        import os, subprocess, tempfile
        from pathlib import Path
        from jsonschema import validate
        system = (prompt + "\nReturn only a JSON object conforming to the supplied JSON schema. "
                  "Do not run commands or read files; everything needed is in this message.")
        # Empty workdir, read-only sandbox, no user config/rules/session: nothing but the payload is visible.
        with tempfile.TemporaryDirectory(prefix='sizing-input-') as work:
            schema_file = Path(work) / 'schema.json'
            answer_file = Path(work) / 'answer.txt'
            schema_file.write_text(dumps(schema))
            proc = subprocess.run(
                [find_codex(), "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
                 "--ignore-rules", "-s", "read-only", "-C", work, "-m", self.model,
                 "--output-schema", str(schema_file), "--json", "-o", str(answer_file), "-"],
                input=system + "\n\nINPUT_JSON:\n" + dumps(payload),
                capture_output=True, text=True, timeout=900)
            text = answer_file.read_text() if answer_file.exists() else ''
        usage = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "turn.completed":
                u = event.get("usage") or {}
                pt = u.get("input_tokens", 0)
                usage = {"prompt_tokens": pt, "completion_tokens": u.get("output_tokens", 0),
                         "total_tokens": pt + u.get("output_tokens", 0)}
            elif event.get("type") in ("error", "turn.failed"):
                raise RuntimeError(f"codex error ({self.model}): {line[:500]}")
        if proc.returncode or not text.strip():
            raise RuntimeError(f"codex CLI failed ({self.model}): {(proc.stderr or proc.stdout)[-500:]}")
        record["usage"] = usage
        record["raw_response"] = text
        result = json.loads(text)
        validate(result, schema)
        record["status"] = "passed"
        return result
