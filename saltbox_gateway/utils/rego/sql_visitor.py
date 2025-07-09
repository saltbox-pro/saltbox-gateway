from typing import Any, ClassVar

from saltbox_gateway.utils.rego import ast, sql


class SQLQueryVisitor(ast.RegoNodeVisitor):
    _sql_relation_operators: ClassVar[dict[str, str]] = {
        'internal.member_2': 'in',
        'eq': '=',
        'equal': '=',
        'neq': '!=',
        'lt': '<',
        'gt': '>',
        'lte': '<=',
        'gte': '>=',
    }
    _sql_call_operators: ClassVar[dict[str, str]] = {
        'abs': 'abs',
    }

    def __init__(self, from_table: str) -> None:
        self._from_table: str = from_table
        self._joins: list[tuple[set[str], Any]] = []
        self._conjunctions: list[sql.Conjunction] = []
        self._tables: set[str] = set()
        self._relations: list[Any] = []
        self._operands: list[list[Any]] = []

    def visit_QuerySet(self, node: ast.QuerySet) -> sql.Union:  # noqa: N802
        for q in node.queries:
            self.visit(q)
        clauses: list[Any] = []
        if self._conjunctions:
            clauses = [sql.Where(sql.Disjunction(self._conjunctions))]
        for tables, conj in self._joins:
            pred = sql.InnerJoin(tables, conj)
            clauses.append(pred)
        return sql.Union(clauses)

    def visit_Query(self, node: ast.Query) -> None:  # noqa: N802
        for expr in node.exprs:
            self.visit(expr)
        conj = sql.Conjunction(self._relations)
        if len(self._tables) > 1:
            self._tables.discard(self._from_table)
            self._joins.append((set(self._tables), conj))
        else:
            self._conjunctions.append(conj)
        self._tables = set()
        self._relations = []

    def visit_Expr(self, node: ast.Expr) -> None:  # noqa: N802
        if getattr(node, 'ignore', False) or not node.is_call():
            return
        if len(node.operands) != 2:
            msg = 'Invalid expression: too many arguments'
            raise ast.RegoNodeVisitorError(msg)
        op = node.op()
        if op not in self._sql_relation_operators:
            msg = f'Operator not supported: {op}'
            raise ast.RegoNodeVisitorError(msg)
        sql_op = sql.RelationOp(self._sql_relation_operators[op])
        self._operands.append([])
        for term in node.operands:
            self.visit(term)
        sql_operands = self._operands.pop()
        self._relations.append(sql.Relation(sql_op, *sql_operands))

    def visit_Term(self, node: ast.Term) -> None:  # noqa: N802
        v = node.value
        if isinstance(v, ast.Scalar):
            self._operands[-1].append(sql.Constant(v.value))
        elif isinstance(v, ast.Ref) and len(v.terms) == 3:
            table = v.terms[1].value.value
            self._tables.add(table)
            col = sql.Column(v.terms[2].value.value, table)
            self._operands[-1].append(col)
        elif isinstance(v, ast.Call):
            op = v.op()
            if op not in self._sql_call_operators:
                msg = f'Call operator not supported: {op}'
                raise ast.RegoNodeVisitorError(msg)
            sql_op = self._sql_call_operators[op]
            self._operands.append([])
            for term in v.operands:
                self.visit(term)
            sql_operands = self._operands.pop()
            self._operands[-1].append(sql.Call(sql_op, sql_operands))
        elif isinstance(v, ast.Array):
            self._operands[-1].append(sql.Array([sql.Constant(t.value.value) for t in v.terms]))
        elif isinstance(v, ast.Set):
            self._operands[-1].append(sql.Array([sql.Constant(t.value.value) for t in v.terms]))
        else:
            msg = f'Invalid term: type not supported: {v.__class__.__name__}'
            raise ast.RegoNodeVisitorError(msg)

    def generic_visit(self, node: ast.RegoASTNode) -> Any:
        """Change Generic visit."""
        msg = f'Node of type {type(node).__name__} is not supported'
        raise ast.RegoNodeVisitorError(msg)
