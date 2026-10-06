import json
from analog_agents.config import load_config, project_path
from analog_agents.client import LocalClient
from agents.sizing_agent.agent import obj

def main():
    schema = obj({"answer": {"type": "integer"}})
    answer = LocalClient(load_config()).ask("Compute the sum, return JSON.", {"question": "19+23=?"}, schema)
    assert answer["answer"] == 42, answer
    project_path("logs/api_test.json").write_text(json.dumps({"status": "passed", "response": answer}))
    print("Local Qwen API: PASS", answer)

if __name__ == "__main__":
    main()
