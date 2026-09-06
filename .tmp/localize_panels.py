import ast
import json
from pathlib import Path

paths = list(Path('gui/panels').glob('*.py')) + [
    Path('gui/pages/device_hub.py'), Path('gui/pages/tasks_page.py'),
    Path('gui/widgets/device_context_bar.py'),
]
sources = set()
for path in paths:
    original = path.read_text(encoding='utf-8')
    tree = ast.parse(original)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    lines = original.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line.encode('utf-8')))
    def bounds(node):
        return starts[node.lineno - 1] + node.col_offset, starts[node.end_lineno - 1] + node.end_col_offset
    def ancestors(node):
        while node in parents:
            node = parents[node]
            yield node
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        chain = list(ancestors(node))
        if isinstance(parents.get(node), ast.JoinedStr):
            continue
        if any(isinstance(n, ast.JoinedStr) for n in chain):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Expr) and isinstance(parents.get(parent), (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parents[parent].body[0] is parent:
            continue
        segment = ast.get_source_segment(original, node)
        if not any('\u4e00' <= char <= '\u9fff' for char in segment):
            continue
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id == 'tr':
            sources.add(node.value)
            continue
        if isinstance(node, ast.JoinedStr):
            source = ''
            arguments = []
            used = set()
            for value in node.values:
                if isinstance(value, ast.Constant):
                    source += value.value.replace('{', '{{').replace('}', '}}')
                else:
                    expression = ast.get_source_segment(original, value.value)
                    if isinstance(value.value, ast.Name):
                        name = value.value.id
                    elif isinstance(value.value, ast.Attribute):
                        name = value.value.attr
                    elif isinstance(value.value, ast.Call) and isinstance(value.value.func, ast.Name) and value.value.func.id == 'len':
                        name = 'count'
                    else:
                        name = 'value'
                    candidate = name
                    number = 2
                    while candidate in used:
                        candidate = name + '_' + str(number)
                        number += 1
                    name = candidate
                    used.add(name)
                    conversion = '' if value.conversion == -1 else '!' + chr(value.conversion)
                    spec = ''
                    if value.format_spec:
                        assert all(isinstance(p, ast.Constant) for p in value.format_spec.values)
                        spec = ':' + ''.join(p.value for p in value.format_spec.values)
                    source += '{' + name + conversion + spec + '}'
                    arguments.append(name + '=' + expression)
            replacement = 'tr(' + json.dumps(source, ensure_ascii=False) + ').format(' + ', '.join(arguments) + ')'
        else:
            source = node.value
            replacement = 'tr(' + segment + ')'
        sources.add(source)
        if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in chain):
            continue
        if isinstance(parent, ast.arguments):
            continue
        edits.append((*bounds(node), replacement.encode('utf-8')))
    if edits:
        data = original.encode('utf-8')
        for start, end, replacement in sorted(edits, reverse=True):
            data = data[:start] + replacement + data[end:]
        updated = data.decode('utf-8')
        if 'from gui.i18n import tr' not in updated:
            tree = ast.parse(updated)
            first_gui_import = next((n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith('gui.')), None)
            lines = updated.splitlines(keepends=True)
            if first_gui_import is not None:
                lines.insert(first_gui_import.lineno - 1, 'from gui.i18n import tr\n')
            else:
                last_import = max(n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
                lines.insert(last_import, '\nfrom gui.i18n import tr\n')
            updated = ''.join(lines)
        ast.parse(updated)
        assert path.read_text(encoding='utf-8') == original, 'Concurrent modification: ' + str(path)
        path.write_text(updated, encoding='utf-8', newline='')
Path('.tmp/panels-sources.json').write_text(json.dumps(sorted(sources), ensure_ascii=False, indent=2), encoding='utf-8')
print('sources:', len(sources))
