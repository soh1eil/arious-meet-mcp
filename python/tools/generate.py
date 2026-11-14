#!/usr/bin/env python3
"""Generate src/arious_meet_mcp/_generated.py from ../spec/tools.json.

Usage: python3 tools/generate.py      (from the python/ directory, or anywhere)
"""

import json
import keyword
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "..", "..", "spec", "tools.json")
OUT = os.path.join(HERE, "..", "src", "arious_meet_mcp", "_generated.py")

typed_dicts = {}  # name -> source


def pascal(s):
    return "".join(p.capitalize() for p in re.split(r"[^A-Za-z0-9]+", s) if p)


def pyname(n):
    return n + "_" if keyword.iskeyword(n) or n in ("self",) else n


def esc(s):
    return s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"').strip()


def py_type(s, hint):
    t = s.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        inner = py_type({**s, "type": non_null[0]}, hint) if non_null else "Any"
        return inner + " | None" if "null" in t else inner
    if "enum" in s:
        return "Literal[%s]" % ", ".join(json.dumps(v) for v in s["enum"])
    if t == "string":
        return "str"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "array":
        return "list[%s]" % py_type(s.get("items") or {}, hint + "Item")
    if t == "object":
        props = s.get("properties")
        if not props:
            return "dict[str, Any]"
        name = hint
        req = set(s.get("required", []))
        if not all(k.isidentifier() and not keyword.iskeyword(k) for k in props):
            return "dict[str, Any]"
        fr = [(k, py_type(v, hint + pascal(k))) for k, v in props.items() if k in req]
        fo = [(k, py_type(v, hint + pascal(k))) for k, v in props.items() if k not in req]
        lines = []
        base = ""
        if fr:
            lines.append(
                "class _%sReq(TypedDict):\n%s" % (name, "\n".join("    %s: %s" % kv for kv in fr))
            )
            base = "_%sReq, " % name
        lines.append(
            'class %s(%stotal=False):\n    """Object argument of a tool."""\n%s'
            % (
                name,
                base if fr else "TypedDict, ",
                "\n".join("    %s: %s" % kv for kv in fo) or "    pass",
            )
        )
        typed_dicts[name] = "\n\n\n".join(lines)
        return name
    return "Any"


def method(tool, is_async):
    name = tool["name"]
    schema = tool["inputSchema"]
    props = schema.get("properties", {})
    required = [k for k in schema.get("required", []) if k in props]
    optional = [k for k in props if k not in required]
    hint_base = pascal(name)
    sig, doc_args = [], []
    for k in required:
        ty = py_type(props[k], hint_base + pascal(k))
        if k == "model_name":
            sig.append("%s: str | None = None" % pyname(k))
        else:
            sig.append("%s: %s" % (pyname(k), ty))
    # model_name has a default so it must follow the required params
    sig = [s for s in sig if not s.startswith("model_name:")] + [
        s for s in sig if s.startswith("model_name:")
    ]
    kw = []
    for k in optional:
        ty = py_type(props[k], hint_base + pascal(k))
        if k == "model_name":
            kw.append("%s: str | None = None" % pyname(k))
        else:
            kw.append("%s: %s | None = None" % (pyname(k), ty))
    # required-without-default can't follow defaulted: required model_name goes to kw-only
    sig_req = [s for s in sig if "= None" not in s]
    sig_def = [s for s in sig if "= None" in s]
    params = sig_req
    if sig_def or kw:
        params = params + ["*"] + sig_def + kw
    for k, v in props.items():
        d = v.get("description")
        if d:
            doc_args.append("            %s: %s" % (pyname(k), esc(d).replace("\n", " ")))
    items = ", ".join("%s: %s" % (json.dumps(k), pyname(k)) for k in props)
    call = "self._call_tool(%s, {%s}%s)" % (
        json.dumps(name),
        items,
        ", _meta=True" if False else "",
    )
    desc = esc(tool.get("description", ""))
    doc = '        """%s' % desc
    if doc_args:
        doc += "\n\n        Args:\n" + "\n".join(doc_args)
    doc += '\n        """'
    aw = "async " if is_async else ""
    rv = "await " if is_async else ""
    plist = "".join("        %s,\n" % p for p in params)
    s = "    %sdef %s(\n        self,\n%s    ) -> ToolResult:\n%s\n        return %s%s\n" % (
        aw,
        name,
        plist,
        doc,
        rv,
        call,
    )
    return s


def main():
    with open(SPEC, encoding="utf-8") as f:
        tools = json.load(f)["tools"]
    meta = {}
    sync_methods, async_methods = [], []
    for t in tools:
        a = t.get("annotations", {})
        props = t["inputSchema"].get("properties", {})
        meta[t["name"]] = {
            "read_only": bool(a.get("readOnlyHint")),
            "idempotent": bool(a.get("idempotentHint")),
            "client_message_id": "client_message_id" in props,
            "model_name": "model_name" in props,
        }
        sync_methods.append(method(t, False))
    for t in tools:
        async_methods.append(method(t, True))
    # Python wire names that are keywords (e.g. "from") need the trailing underscore mapped back.
    out = [
        '"""GENERATED by tools/generate.py from spec/tools.json. Do not edit by hand."""',
        "# ruff: noqa",
        "from __future__ import annotations",
        "",
        "from typing import Any, Literal, TypedDict",
        "",
        "from ._types import ToolResult",
        "",
        "",
        "# name -> annotations that decide retry safety and automatic arguments.",
        "TOOL_META: dict[str, dict[str, bool]] = " + repr(meta),
        "",
        "",
    ]
    for n in sorted(typed_dicts):
        out.append(typed_dicts[n])
        out.append("\n")
    out.append('class ToolsMixin:\n    """Typed synchronous wrappers, one per server tool."""\n')
    out.append(
        "    def _call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:  # pragma: no cover\n        raise NotImplementedError\n"
    )
    out.extend(sync_methods)
    out.append(
        '\nclass AsyncToolsMixin:\n    """Typed asynchronous wrappers, one per server tool."""\n'
    )
    out.append(
        "    async def _call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:  # pragma: no cover\n        raise NotImplementedError\n"
    )
    out.extend(async_methods)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("wrote %s (%d tools)" % (os.path.relpath(OUT), len(tools)))


if __name__ == "__main__":
    main()
