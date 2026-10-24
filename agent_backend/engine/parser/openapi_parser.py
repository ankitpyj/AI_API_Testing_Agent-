import json
import urllib.request


OPENAPI_URL = "http://127.0.0.1:8000/openapi.json"


HTTP_METHODS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "options",
    "head"
}


def load_openapi(url):
    """
    Fetch OpenAPI specification from the target API.
    """

    with urllib.request.urlopen(url) as response:
        data = response.read()

    return json.loads(data)


def resolve_schema(schema, openapi_data, seen_refs=None):
    """
    Resolve $ref, anyOf, and oneOf schemas recursively, including
    references inside object properties and array items.
    Protects against cyclic / recursive $ref loops using seen_refs.
    """

    if not isinstance(schema, dict):
        return schema

    if seen_refs is None:
        seen_refs = set()

    # Handle $ref
    if "$ref" in schema:
        ref_path = schema["$ref"]
        if ref_path in seen_refs:
            # Cyclic or recursive reference encountered — prevent infinite recursion
            return schema

        ref_name = ref_path.split("/")[-1]

        resolved = (
            openapi_data
            .get("components", {})
            .get("schemas", {})
            .get(ref_name)
        )
        if resolved is None:
            resolved = openapi_data.get("$defs", {}).get(ref_name, {})

        new_seen = seen_refs | {ref_path}
        return resolve_schema(resolved, openapi_data, seen_refs=new_seen)

    # Clone schema so we don't mutate openapi_data in-place
    resolved_schema = dict(schema)

    # Handle anyOf
    if "anyOf" in resolved_schema and isinstance(resolved_schema["anyOf"], list):
        non_null_options = [opt for opt in resolved_schema["anyOf"] if isinstance(opt, dict) and opt.get("type") != "null"]
        has_null = any(isinstance(opt, dict) and opt.get("type") == "null" for opt in resolved_schema["anyOf"])
        if has_null and len(non_null_options) == 1:
            resolved = resolve_schema(non_null_options[0], openapi_data, seen_refs=seen_refs)
            if isinstance(resolved, dict):
                merged = dict(resolved_schema)
                merged.pop("anyOf", None)
                merged.update(resolved)
                merged["nullable"] = True
                return merged
            return resolved
        else:
            resolved_schema["anyOf"] = [
                resolve_schema(opt, openapi_data, seen_refs=seen_refs)
                for opt in resolved_schema["anyOf"]
            ]
            if has_null:
                resolved_schema["nullable"] = True

    # Handle oneOf
    if "oneOf" in resolved_schema and isinstance(resolved_schema["oneOf"], list):
        non_null_options = [opt for opt in resolved_schema["oneOf"] if isinstance(opt, dict) and opt.get("type") != "null"]
        has_null = any(isinstance(opt, dict) and opt.get("type") == "null" for opt in resolved_schema["oneOf"])
        if has_null and len(non_null_options) == 1:
            resolved = resolve_schema(non_null_options[0], openapi_data, seen_refs=seen_refs)
            if isinstance(resolved, dict):
                merged = dict(resolved_schema)
                merged.pop("oneOf", None)
                merged.update(resolved)
                merged["nullable"] = True
                return merged
            return resolved
        else:
            resolved_schema["oneOf"] = [
                resolve_schema(opt, openapi_data, seen_refs=seen_refs)
                for opt in resolved_schema["oneOf"]
            ]
            if has_null:
                resolved_schema["nullable"] = True

    # Recursively resolve nested object properties
    if "properties" in resolved_schema and isinstance(resolved_schema["properties"], dict):
        new_props = {}
        for prop_name, prop_schema in resolved_schema["properties"].items():
            new_props[prop_name] = resolve_schema(
                prop_schema,
                openapi_data,
                seen_refs=seen_refs
            )
        resolved_schema["properties"] = new_props

    # Recursively resolve array items
    if "items" in resolved_schema and isinstance(resolved_schema["items"], dict):
        resolved_schema["items"] = resolve_schema(
            resolved_schema["items"],
            openapi_data,
            seen_refs=seen_refs
        )

    return resolved_schema


def extract_schema_details(schema, openapi_data):
    """
    Extract useful information from an OpenAPI schema.
    """

    # Resolve $ref / anyOf / oneOf
    schema = resolve_schema(
        schema,
        openapi_data
    )

    properties = schema.get(
        "properties",
        {}
    )

    required = schema.get(
        "required",
        []
    )

    fields = []

    for field_name, raw_field_data in properties.items():
        if not isinstance(raw_field_data, dict):
            raw_field_data = {}

        field_data = resolve_schema(
            raw_field_data,
            openapi_data
        )
        if not isinstance(field_data, dict):
            field_data = {}

        # Check whether field allows null (explicit nullable or anyOf/oneOf null branch)
        nullable = False
        if raw_field_data.get("nullable") is True or field_data.get("nullable") is True:
            nullable = True
        elif "anyOf" in raw_field_data and any(isinstance(opt, dict) and opt.get("type") == "null" for opt in raw_field_data["anyOf"]):
            nullable = True
        elif "anyOf" in field_data and any(isinstance(opt, dict) and opt.get("type") == "null" for opt in field_data["anyOf"]):
            nullable = True
        elif "oneOf" in raw_field_data and any(isinstance(opt, dict) and opt.get("type") == "null" for opt in raw_field_data["oneOf"]):
            nullable = True
        elif "oneOf" in field_data and any(isinstance(opt, dict) and opt.get("type") == "null" for opt in field_data["oneOf"]):
            nullable = True

        field_type = field_data.get("type") or raw_field_data.get("type")
        field_format = field_data.get("format") or raw_field_data.get("format")

        # If type/format not directly present, check non-null options in anyOf / oneOf
        if not field_type:
            for container in (field_data, raw_field_data):
                for branch in ("anyOf", "oneOf"):
                    options = container.get(branch)
                    if isinstance(options, list):
                        non_null_opts = [
                            opt for opt in options
                            if isinstance(opt, dict) and opt.get("type") != "null"
                        ]
                        if non_null_opts:
                            opt_resolved = resolve_schema(non_null_opts[0], openapi_data)
                            if isinstance(opt_resolved, dict):
                                field_type = opt_resolved.get("type")
                                if not field_format:
                                    field_format = opt_resolved.get("format")
                            if field_type:
                                break
                if field_type:
                    break

        # Create field information
        field = {
            "name": field_name,
            "type": field_type,
            "format": field_format,
            "required": field_name in required,
            "nullable": nullable
        }

        # Optional constraints
        for constraint in (
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "pattern",
            "enum",
            "default",
            "example"
        ):
            val = field_data.get(constraint)
            if val is None:
                val = raw_field_data.get(constraint)
            if val is not None:
                field[constraint] = val

        fields.append(field)

    return fields


def extract_endpoints(openapi_data):

    endpoints = []

    paths = openapi_data.get("paths", {})

    for path, path_data in paths.items():

        for method, operation in path_data.items():

            if method.lower() not in HTTP_METHODS:
                continue

            endpoint = {
                "method": method.upper(),
                "path": path,
                "summary": operation.get("summary"),
                "description": operation.get("description"),
                "parameters": [],
                "request_body": None,
                "responses": []
            }

            # -------------------------
            # Parameters
            # -------------------------
            
            # Parameters can be defined at the
            # path level or operation level.
            
            path_parameters = path_data.get(
                "parameters",
                []
            )
            
            operation_parameters = operation.get(
                "parameters",
                []
            )
            
            all_parameters = (
                path_parameters +
                operation_parameters
            )
            
            for parameter in all_parameters:
                raw_param_schema = parameter.get(
                    "schema",
                    {}
                )
                param_schema = resolve_schema(raw_param_schema, openapi_data) if isinstance(raw_param_schema, dict) else {}

                endpoint["parameters"].append({
                    "name": parameter.get("name"),
                    "location": parameter.get("in"),
                    "required": parameter.get(
                        "required",
                        False
                    ),
                    "type": param_schema.get("type"),
                    "format": param_schema.get("format"),
                    "nullable": param_schema.get("nullable", False),
                    "example": param_schema.get("example", parameter.get("example")),
                    "default": param_schema.get("default", parameter.get("default"))
                })
            
            # -------------------------
            # Request Body
            # -------------------------

            request_body = operation.get("requestBody")

            if request_body:

                content = request_body.get("content", {})

                json_content = content.get(
                    "application/json"
                )

                if json_content:

                    schema = json_content.get(
                        "schema",
                        {}
                    )

                    endpoint["request_body"] = {
                        "content_type": "application/json",
                        "required": request_body.get(
                            "required",
                            False
                        ),
                        "fields": extract_schema_details(
                            schema,
                            openapi_data
                        )
                    }

            # -------------------------
            # Responses
            # -------------------------

            for status_code, response_data in operation.get(
                "responses",
                {}
            ).items():
                
                endpoint["responses"].append({
                    "status_code": status_code,
                    "description": response_data.get("description"),
                    "content": response_data.get("content", {})
                })

            endpoints.append(endpoint)

    return endpoints


def print_endpoint_details(endpoint):

    print("\n" + "=" * 60)

    print(
        f"{endpoint['method']} {endpoint['path']}"
    )

    if endpoint["summary"]:
        print(
            f"Summary: {endpoint['summary']}"
        )

    # Parameters

    if endpoint["parameters"]:

        print("\nParameters:")

        for parameter in endpoint["parameters"]:

            print(
                f"  - {parameter['name']}"
                f" | location={parameter['location']}"
                f" | type={parameter['type']}"
                f" | required={parameter['required']}"
            )

    # Request body

    if endpoint["request_body"]:

        body = endpoint["request_body"]

        print("\nRequest Body:")

        for field in body["fields"]:

            print(
                f"  - {field['name']}"
                f" | type={field['type']}"
                f" | format={field['format']}"
                f" | required={field['required']}"
            )

    # Responses

    if endpoint["responses"]:

        print("\nExpected Responses:")

        for response in endpoint["responses"]:

            print(
                f"  - {response['status_code']}"
                f" → {response['description']}"
            )

if __name__ == "__main__":

    openapi_data = load_openapi(
        OPENAPI_URL
    )

    endpoints = extract_endpoints(
        openapi_data
    )

    for endpoint in endpoints:
        print_endpoint_details(endpoint)