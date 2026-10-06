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
        response = self.api.chat.completions.create(
            model=self.config["served_model"],
            messages=[{"role": "system", "content": prompt + "\nReturn only a JSON object conforming to this schema: " + json.dumps(schema)},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            temperature=self.config["temperature"], max_tokens=self.config["max_tokens"],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}, "guided_json": schema})
        choice = response.choices[0]
        if response.usage is not None:
            record["usage"] = {"prompt_tokens": response.usage.prompt_tokens,
                               "completion_tokens": response.usage.completion_tokens,
                               "total_tokens": response.usage.total_tokens}
        if choice.finish_reason != "stop":
            raise ValueError(f"Incomplete model output: {choice.finish_reason}")
        result = json.loads(choice.message.content)
        from jsonschema import validate
        validate(result, schema)
        record["status"] = "passed"
        return result
