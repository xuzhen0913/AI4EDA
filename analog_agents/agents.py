from .config import project_path

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

TEXT = {"type": "string"}
PARAMETERS = obj({
    "input_w_um": {"type": "number", "minimum": 1, "maximum": 200},
    "input_l_um": {"type": "number", "minimum": 0.18, "maximum": 5},
    "load_w_um": {"type": "number", "minimum": 1, "maximum": 400},
    "stage2_w_um": {"type": "number", "minimum": 1, "maximum": 400},
    "bias_ua": {"type": "number", "minimum": 1, "maximum": 300},
    "compensation_pf": {"type": "number", "minimum": 0.1, "maximum": 20}
})
SCHEMAS = {
    "architecture": obj({"topology": {"type": "string", "enum": ["two_stage_cmos_opamp"]}, "rationale": TEXT, "assumptions": {"type": "array", "items": TEXT}}),
    "sizing": obj({"parameters": PARAMETERS, "rationale": TEXT}),
    "simulation": obj({"analyses": {"type": "array", "items": {"type": "string", "enum": ["op", "ac", "tran"]}, "minItems": 1}, "rationale": TEXT}),
    "optimization": obj({"parameters": PARAMETERS, "rationale": TEXT, "stop": {"type": "boolean"}})
}

class Agent:
    def __init__(self, name, client):
        self.name, self.client = name, client
        self.prompt = project_path(f"prompts/{name}.md").read_text()

    def run(self, context):
        return self.client.ask(self.prompt, context, SCHEMAS[self.name], agent_name=self.name)
