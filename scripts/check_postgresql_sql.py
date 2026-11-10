"""Compile GPHEM's static application statements against an isolated schema."""
import ast
from pathlib import Path


def statements():
    root = Path(__file__).resolve().parent.parent
    queries = set()
    for path in [root / 'app.py', *(root / 'services').glob('*.py'), *(root / 'web').glob('*.py')]:
        if path.name == 'postgres.py':
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr not in ('execute', 'executemany') or not node.args:
                continue
            try:
                query = ast.literal_eval(node.args[0])
            except (ValueError, TypeError):
                continue
            if isinstance(query, str) and query.lstrip().upper().startswith(('SELECT', 'INSERT', 'UPDATE', 'DELETE')) and 'sqlite_master' not in query:
                queries.add(query)
    return sorted(queries)


def check(db):
    queries = statements()
    for query in queries:
        # EXPLAIN without ANALYZE plans writes without executing them.
        db.execute('EXPLAIN ' + query, [None] * query.count('?')).fetchall()
    return len(queries)
