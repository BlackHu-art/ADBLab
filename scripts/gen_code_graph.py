"""生成 ADBLab 全量代码的 Obsidian 知识图谱（文件/类/方法节点 + 调用/继承/导入/实例化边）。

用法：
    python scripts/gen_code_graph.py

输出：
    docs/code-map/CODE_MAP.md        总索引（MOC，wikilink 到所有文件节点）
    docs/code-map/notes/*.md         每个代码单元一个笔记（[[wikilink]] 互链）

解析策略（尽力而为的静态名字解析）：
    - 导入：import a.b[.c] [as x] / from [.][pkg.]mod import name [as y]
    - 调用：self.x()/cls.x() -> 本类及基类 MRO 中的方法
            from X import f; f() -> X.f
            同模块 f() -> 本模块顶层函数/类
            全局唯一名字 f() -> 全仓库唯一匹配
            Foo() -> 类实例化
    - 继承：class X(Base) -> 解析 Base 到仓库内类
外部库（PySide6/os/shutil 等）与动态名字无法解析时跳过，不产生边。
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "code-map" / "notes"
MOC = ROOT / "docs" / "code-map" / "CODE_MAP.md"

INCLUDE_DIRS = [
    "core", "controllers", "gui", "models", "services", "utils",
    "adblab", "mobileperf", "tests", "scripts",
]
EXCLUDE = {"__pycache__", "mobileperf/extlib"}

BUILTINS = {
    n for n in dir(__builtins__) if isinstance(__builtins__, dict)
} if isinstance(__builtins__, dict) else set(dir(__builtins__))
BUILTINS |= {
    "super", "self", "cls", "True", "False", "None",
    "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
    "RuntimeError", "NotImplementedError", "AttributeError", "OSError",
    "IOError", "IndexError", "StopIteration", "object", "property",
    "staticmethod", "classmethod", "print", "len", "range", "enumerate",
    "zip", "map", "filter", "sorted", "reversed", "isinstance", "issubclass",
    "getattr", "setattr", "hasattr", "iter", "next", "abs", "round", "min",
    "max", "sum", "any", "all", "repr", "hash", "id", "callable", "vars",
    "dir", "globals", "locals", "open", "format", "pow", "divmod", "chr",
    "ord", "bool", "int", "float", "str", "bytes", "bytearray", "list",
    "dict", "tuple", "set", "frozenset", "memoryview", "complex", "slice",
}


def module_of(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "_root"


def first_line(doc: str | None) -> str:
    if not doc:
        return ""
    line = doc.splitlines()[0].strip()
    for ch in "。.":
        if line.endswith(ch):
            line = line[:-1]
    return line[:80]


def expr_name(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return expr_name(node.value)
    return None


def fmt_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = node.args
    parts: list[str] = []
    posonly = list(a.posonlyargs) + list(a.args)
    defaults = [None] * (len(posonly) - len(a.defaults)) + list(a.defaults)
    for i, arg in enumerate(posonly):
        s = arg.arg
        d = defaults[i]
        if d is not None:
            s += "=" + ast.unparse(d)
        parts.append(s)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    for kw, d in zip(a.kwonlyargs, a.kw_defaults):
        s = kw.arg
        if d is not None:
            s += "=" + ast.unparse(d)
        parts.append(s)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return ", ".join(parts)


files: list[tuple[Path, str, ast.Module]] = []
classes: dict[str, dict] = {}
funcs: dict[str, dict] = {}
module_set: set[str] = set()

if (ROOT / "main.py").exists():
    candidates = [ROOT / "main.py"]
else:
    candidates = []
for d in INCLUDE_DIRS:
    base = ROOT / d
    if base.exists():
        candidates += [p for p in base.rglob("*.py")]

for p in sorted(candidates):
    rel = p.relative_to(ROOT).as_posix()
    if any(part in rel for part in EXCLUDE):
        continue
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  [跳过解析失败] {rel}: {exc}")
        continue
    mod = module_of(p)
    module_set.add(mod)
    files.append((p, mod, tree))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            qname = f"{mod}.{node.name}"
            bases = [expr_name(b) for b in node.bases]
            classes[qname] = {
                "module": mod, "file": rel, "name": node.name,
                "bases": [b for b in bases if b],
                "doc": first_line(ast.get_docstring(node)),
                "methods": [],
            }
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mq = f"{qname}.{m.name}"
                    funcs[mq] = {
                        "module": mod, "class": qname, "name": m.name,
                        "is_method": True, "doc": first_line(ast.get_docstring(m)),
                        "args": fmt_args(m), "node": m,
                    }
                    classes[qname]["methods"].append(mq)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qname = f"{mod}.{node.name}"
            funcs[qname] = {
                "module": mod, "class": None, "name": node.name,
                "is_method": False, "doc": first_line(ast.get_docstring(node)),
                "args": fmt_args(node), "node": node,
            }

basename_index: dict[str, list[str]] = defaultdict(list)
for q in list(classes) + list(funcs):
    basename_index[q.rsplit(".", 1)[-1]].append(q)


def resolve_qualified(name: str, cur_module: str) -> str | None:
    if not name:
        return None
    if "." in name:
        if name in classes or name in funcs:
            return name
        cand = basename_index.get(name.rsplit(".", 1)[-1], [])
        return cand[0] if len(cand) == 1 else None
    same = f"{cur_module}.{name}"
    if same in classes or same in funcs:
        return same
    cand = basename_index.get(name, [])
    return cand[0] if len(cand) == 1 else None


for qname, info in classes.items():
    resolved: list[str] = []
    for bn in info["bases"]:
        target = resolve_qualified(bn, info["module"])
        if target in classes:
            resolved.append(target)
    info["resolved_bases"] = resolved


def mro(qname: str) -> list[str]:
    seen: list[str] = []
    def dfs(c: str) -> None:
        if c in seen:
            return
        seen.append(c)
        for b in classes.get(c, {}).get("resolved_bases", []):
            dfs(b)
    dfs(qname)
    return seen


imports: dict[str, dict] = {}


def resolve_relative(cur: str, level: int, module: str | None) -> str:
    parts = cur.split(".")
    base = ".".join(parts[:-level]) if 0 < level <= len(parts) else ""
    if module:
        return f"{base}.{module}" if base else module
    return base


for _p, mod, tree in files:
    mod_imports: dict[str, str] = {}
    from_imports: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                mod_imports[local] = alias.name
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(mod, node.level, node.module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                from_imports[local] = (base, alias.name)
    imports[mod] = {"mod": mod_imports, "from": from_imports}


edges: dict[str, set[tuple[str, str]]] = defaultdict(set)


def add(kind: str, src: str, dst: str) -> None:
    if dst and src != dst:
        edges[kind].add((src, dst))


for q, info in classes.items():
    add("define", info["module"], q)
    for mq in info["methods"]:
        add("define", q, mq)
for q, info in funcs.items():
    if not info["is_method"]:
        add("define", info["module"], q)

# 聚焦调用关系：不再生成 import（文件→文件）边


def local_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
        names.add(a.arg)
    if node.args.vararg:
        names.add(node.args.vararg.arg)
    if node.args.kwarg:
        names.add(node.args.kwarg.arg)
    for n in ast.walk(node):
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            if isinstance(n.target, ast.Name):
                names.add(n.target.id)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
        elif isinstance(n, ast.ExceptHandler):
            if n.name:
                names.add(n.name)
        elif isinstance(n, ast.NamedExpr):
            if isinstance(n.target, ast.Name):
                names.add(n.target.id)
    return names


def resolve_call_target(
    node: ast.expr, mod: str, cls_qname: str | None, locals_: set[str]
) -> str | None:
    imp = imports.get(mod, {"mod": {}, "from": {}})
    from_imp = imp["from"]
    mod_imp = imp["mod"]

    if isinstance(node, ast.Name):
        name = node.id
        if name in BUILTINS or name in locals_:
            return None
        if name in from_imp:
            m, orig = from_imp[name]
            q = f"{m}.{orig}"
            return q if (q in classes or q in funcs) else None
        q = f"{mod}.{name}"
        if q in classes or q in funcs:
            return q
        cand = basename_index.get(name, [])
        return cand[0] if len(cand) == 1 else None

    if isinstance(node, ast.Attribute):
        attr = node.attr
        value = node.value
        if isinstance(value, ast.Name):
            obj = value.id
            if obj in ("self", "cls") and cls_qname:
                for c in mro(cls_qname):
                    q = f"{c}.{attr}"
                    if q in funcs:
                        return q
                return None
            if obj in mod_imp:
                m = mod_imp[obj]
                q = f"{m}.{attr}"
                if q in classes or q in funcs:
                    return q
                return None
            if obj in from_imp:
                cand = [c for c in basename_index.get(attr, []) if c in funcs]
                return cand[0] if len(cand) == 1 else None
            cand = [c for c in basename_index.get(attr, []) if c in funcs]
            return cand[0] if len(cand) == 1 else None
        return None

    return None


def analyze_calls(fn_qname: str, info: dict) -> None:
    node = info["node"]
    mod = info["module"]
    cls_q = info["class"]
    locals_ = local_names(node)
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        target = resolve_call_target(call.func, mod, cls_q, locals_)
        if target is None:
            continue
        if target in classes:
            add("instantiate", fn_qname, target)
        elif target in funcs:
            add("call", fn_qname, target)


for q, info in funcs.items():
    analyze_calls(q, info)

# 聚焦调用关系：不再生成 inherit（类→基类）边


basename_map: dict[str, str] = {}
used: set[str] = set()


def assign(name: str, kind: str) -> str:
    base = name
    if base in used:
        base = f"{name} ({kind})"
    n = 2
    while base in used:
        base = f"{name} ({kind}#{n})"
        n += 1
    used.add(base)
    return base


for mod in sorted(module_set):
    basename_map[mod] = assign(mod, "module")
for q in sorted(classes):
    basename_map[q] = assign(q, "class")
for q in sorted(funcs):
    basename_map[q] = assign(q, "method" if funcs[q]["is_method"] else "function")


def wl(qname: str) -> str:
    return basename_map.get(qname, qname)


def note_header(kind: str, title: str) -> list[str]:
    return ["---", f"kind: {kind}", "---", "", f"# {title}", ""]


def render_file(mod: str, path: Path, tree: ast.Module) -> str:
    lines = note_header("file", mod)
    doc = first_line(ast.get_docstring(tree))
    if doc:
        lines += [f"> {doc}", ""]
    lines += [f"- 路径：{path.relative_to(ROOT).as_posix()}", ""]

    cls = sorted(q for q, i in classes.items() if i["module"] == mod)
    fns = sorted(q for q, i in funcs.items() if i["module"] == mod and not i["is_method"])

    if cls:
        lines += ["## 类", ""]
        for q in cls:
            lines.append(f"- [[{wl(q)}]] — {classes[q]['doc'] or '（无 docstring）'}")
        lines.append("")
    if fns:
        lines += ["## 函数", ""]
        for q in fns:
            lines.append(f"- [[{wl(q)}]] — {funcs[q]['doc'] or '（无 docstring）'}")
        lines.append("")

    return "\n".join(lines) + "\n"


def render_class(q: str) -> str:
    info = classes[q]
    lines = note_header("class", q.rsplit(".", 1)[-1])
    lines += [f"- 模块：[[{wl(info['module'])}]]", f"- 全名：{q}", ""]
    if info["doc"]:
        lines += [f"> {info['doc']}", ""]
    if info["methods"]:
        lines += ["## 方法", ""]
        for mq in info["methods"]:
            lines.append(f"- [[{wl(mq)}]] — {funcs[mq]['doc'] or '（无 docstring）'}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_func(q: str) -> str:
    info = funcs[q]
    kind = "method" if info["is_method"] else "function"
    label = q.rsplit(".", 1)[-1]
    lines = note_header(kind, f"{label}({info['args']})")
    owner = info["class"] if info["is_method"] else info["module"]
    lines += [f"- 定义于：[[{wl(owner)}]]", f"- 全名：{q}", ""]
    if info["doc"]:
        lines += [f"> {info['doc']}", ""]
    calls = sorted(t for s, t in edges["call"] if s == q)
    insts = sorted(t for s, t in edges["instantiate"] if s == q)
    if calls:
        lines += ["## 调用", ""]
        for t in calls:
            lines.append(f"- [[{wl(t)}]]")
        lines.append("")
    if insts:
        lines += ["## 实例化", ""]
        for t in insts:
            lines.append(f"- [[{wl(t)}]]")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_moc() -> str:
    lines = ["---", "title: 入口（main）", "kind: entry", "---", ""]
    lines += ["# 入口（main）", ""]
    lines += [
        "> ADBLab 程序入口。代码调用关系图谱：以 main 为根，函数/方法之间的调用与类实例化互链，",
        "反向关系由 Obsidian 反链自动呈现。",
        "",
    ]
    lines += [f"- 文件：{len(module_set)}　类：{len(classes)}　函数/方法：{len(funcs)}", ""]
    entry_funcs = sorted(
        q for q, i in funcs.items() if i["module"] == "main" and not i["is_method"]
    )
    lines += ["## 程序入口", ""]
    for q in entry_funcs:
        lines.append(f"- [[{wl(q)}]] — {funcs[q]['doc'] or '（无 docstring）'}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.md"):
        old.unlink()

    for p, mod, tree in files:
        (OUT_DIR / (basename_map[mod] + ".md")).write_text(
            render_file(mod, p, tree), encoding="utf-8"
        )
    for q in classes:
        (OUT_DIR / (basename_map[q] + ".md")).write_text(render_class(q), encoding="utf-8")
    for q in funcs:
        (OUT_DIR / (basename_map[q] + ".md")).write_text(render_func(q), encoding="utf-8")

    MOC.parent.mkdir(parents=True, exist_ok=True)
    MOC.write_text(render_moc(), encoding="utf-8")

    n_notes = len(module_set) + len(classes) + len(funcs)
    print(
        f"节点：文件 {len(module_set)}，类 {len(classes)}，"
        f"函数/方法 {len(funcs)}，合计 {n_notes}"
    )
    print(
        f"边：import {len(edges['import'])}，inherit {len(edges['inherit'])}，"
        f"define {len(edges['define'])}，call {len(edges['call'])}，"
        f"instantiate {len(edges['instantiate'])}"
    )
    print(f"输出：{MOC.relative_to(ROOT).as_posix()} + {OUT_DIR.relative_to(ROOT).as_posix()}/*.md")


if __name__ == "__main__":
    main()
