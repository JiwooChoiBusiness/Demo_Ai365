"""에이전트/커넥터 능력과 JSON 입출력 명세. 기존 등록 화면은 그대로 사용한다."""
import copy
import json
from app.execution import PlanError

TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def validate_schema(schema):
    if not isinstance(schema, dict) or not isinstance(schema.get("type", "object"), str) or schema.get("type", "object") not in TYPES:
        raise PlanError("Tool 스키마의 type이 올바르지 않습니다")
    if schema.get("type", "object") == "object":
        props, required = schema.get("properties", {}), schema.get("required", [])
        if not isinstance(props, dict) or not isinstance(required, list) or any(not isinstance(k, str) or k not in props for k in required):
            raise PlanError("Tool 필수 필드는 properties에 선언해야 합니다")
        for child in props.values():
            validate_schema(child)
    if "items" in schema:
        validate_schema(schema["items"])
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise PlanError("Tool enum은 목록이어야 합니다")


def check(value, schema, path="입력"):
    typ = schema.get("type", "object")
    if not isinstance(value, TYPES[typ]) or (typ in ("integer", "number") and isinstance(value, bool)):
        raise PlanError(f"{path}: {typ} 타입이 필요합니다")
    if "enum" in schema and value not in schema["enum"]:
        raise PlanError(f"{path}: 허용된 값이 아닙니다")
    if typ == "object":
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value or value[key] is None or (isinstance(value[key], str) and not value[key].strip()):
                raise PlanError(f"{path}.{key}: 필수 값이 없습니다")
        for key, child in value.items():
            if key in props:
                check(child, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise PlanError(f"{path}.{key}: 선언되지 않은 필드입니다")
    elif typ == "array" and "items" in schema:
        for i, child in enumerate(value):
            check(child, schema["items"], f"{path}[{i}]")


def contract(connector):
    from app.flow_api_call import required_inputs
    explicit = (connector.get("api") or {}).get("tool_contract")
    if explicit is not None:
        validate_contract(explicit)
        spec = copy.deepcopy(explicit)
        spec.pop("legacy", None)
        return spec
    # 레거시 조회의 빈 필터=전체 조회 계약을 보존한다. 신규 명세는 조회에도 required를 적용한다.
    # 입력값 설명과 명시한 타입을 공유한다. 타입이 없는 기존 API만 느슨한 입력을 유지한다.
    # Input docs carry explicit types; old records without a type retain their loose contract.
    from app.flow_api_call import input_specs
    names = required_inputs(connector.get("api") or {})
    props = {}
    for spec in input_specs(connector.get("api") or {}):
        prop = {}
        if spec.get("type"):
            prop["type"] = spec["type"]
        if spec.get("description"):
            prop["description"] = spec["description"]
        if spec.get("example"):
            prop["examples"] = [spec["example"]]
        # 기본값(2026-09-14, api.input_docs[].default) — 비어 있지 않을 때만 스키마 default 로 실어 prepare_inputs 가 채운다
        # (빈 문자열을 넣으면 모든 입력이 조용히 선택 사항이 된다) / a non-empty default rides as the schema default so
        # prepare_inputs fills it (an empty string would silently make every input optional)
        if spec.get("default"):
            prop["default"] = spec["default"]
        props[spec["name"]] = prop
    return {"version": 1, "input_schema": {"type": "object", "properties": {k: props.get(k, {}) for k in names},
            "required": [s["name"] for s in input_specs(connector.get("api") or {}) if s.get("required", True)]
                        if connector.get("kind") == "action" else []},
            "retry_safe": connector.get("kind") != "action", "legacy": True}


def validate_contract(spec):
    if not isinstance(spec, dict) or spec.get("version") != 1:
        raise PlanError("tool_contract.version은 1이어야 합니다")
    if not isinstance(spec.get("input_schema"), dict) or spec["input_schema"].get("type", "object") != "object":
        raise PlanError("input_schema는 object 타입이어야 합니다")
    validate_schema(spec["input_schema"])
    if "output_schema" in spec:
        validate_schema(spec["output_schema"])
    if not isinstance(spec.get("retry_safe", False), bool):
        raise PlanError("retry_safe는 불리언이어야 합니다")


def prepare_inputs(connector, inputs, *, coerce_text=False):
    spec = contract(connector)
    values = copy.deepcopy(inputs or {})
    schema = spec["input_schema"]
    for k, prop in schema.get("properties", {}).items():
        if k not in values and "default" in prop:
            values[k] = copy.deepcopy(prop["default"])
        # Forms and variable bindings arrive as text; convert only explicitly typed fields.
        if coerce_text and k in values and isinstance(values[k], str) and prop.get("type") not in (None, "string"):
            try:
                values[k] = json.loads(values[k])
            except ValueError:
                pass
        if k in values and prop.get("type") and values[k] not in (None, ""):
            check(values[k], prop, f"입력.{k}")
    missing = [k for k in schema.get("required", []) if k not in values or values[k] is None
               or (isinstance(values[k], str) and not values[k].strip())]
    if not missing and not spec.get("legacy"):
        check(values, schema)
    return values, missing, spec


def prepare_workflow_inputs(connector, inputs, asked=()):
    """Shared by workflow execution and the registration test, including optional inputs."""
    from app.flow_api_call import input_specs
    supplied = set(inputs or {})
    values, missing, spec = prepare_inputs(connector, inputs, coerce_text=True)
    for name in asked:
        if name not in supplied:
            values.pop(name, None)
    explicit = (connector.get("api") or {}).get("tool_contract") is not None
    for field in input_specs(connector.get("api") or {}):
        name = field["name"]
        required = (name in spec["input_schema"].get("required", []) if explicit else field.get("required", True))
        required = required or name in asked
        if required and (name not in values or values[name] is None or (isinstance(values[name], str) and not values[name].strip())):
            if name not in missing:
                missing.append(name)
    return values, missing, spec


def registry(connectors=None):
    from app.agents import AGENT_REGISTRY
    agents = [{"id": k, "description": v["description"], "kind": "agent"} for k, v in AGENT_REGISTRY.items()]
    return agents + [{"id": c["id"], "description": c.get("description", ""), "kind": c.get("kind", "read"),
                      "contract": contract(c)} for c in connectors or []]
