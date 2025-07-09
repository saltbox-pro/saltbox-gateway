from typing import Any, ClassVar, cast

from saltbox_gateway.utils.rego import ast


class MongoQueryVisitor(ast.RegoNodeVisitor):
    _mongo_relation_operators: ClassVar[dict[str, str]] = {
        'eq': '$eq',
        'equal': '$eq',
        'neq': '$ne',
        'lt': '$lt',
        'gt': '$gt',
        'lte': '$lte',
        'gte': '$gte',
        'internal.member_2': '$in',
    }

    def __init__(self) -> None:
        self._queries: list[dict[str, Any]] = []

    def visit(self, node: ast.RegoASTNode) -> dict[str, Any]:
        """Visit node."""
        return cast(dict[str, Any], super().visit(node))

    def visit_QuerySet(self, node: ast.QuerySet) -> dict[str, Any]:  # noqa: N802
        for q in node.queries:
            res = self.visit(q)
            if res:
                self._queries.append(res)
        if not self._queries:
            return {}
        if len(self._queries) == 1:
            return self._queries[0]
        return {'$or': self._queries}

    def visit_Query(self, node: ast.Query) -> dict[str, Any]:  # noqa: N802
        and_clauses = []
        for expr in node.exprs:
            res: dict[str, Any] | None = self.visit(expr)
            if res:
                and_clauses.append(res)
        if not and_clauses:
            return {}
        if len(and_clauses) == 1:
            return and_clauses[0]
        return {'$and': and_clauses}

    def visit_Expr(self, node: ast.Expr) -> dict[str, Any] | None:  # noqa: N802
        if getattr(node, 'ignore', False) or not node.is_call():
            return None

        op = node.op()
        if op not in self._mongo_relation_operators:
            msg = f'Operator not supported: {op}'
            raise ast.RegoNodeVisitorError(msg)
        mongo_op = self._mongo_relation_operators[op]
        operands = node.operands
        if len(operands) != 2:
            msg = 'Only binary expressions supported'
            raise ast.RegoNodeVisitorError(msg)

        lhs_is_field = self._is_field_ref(operands[0])
        rhs_is_field = self._is_field_ref(operands[1])

        # Определяем, где поле, где значение
        if lhs_is_field and not rhs_is_field:
            field, value, direct = self._term_to_field(operands[0]), self._term_to_value(operands[1]), True
        elif not lhs_is_field and rhs_is_field:
            field, value, direct = self._term_to_field(operands[1]), self._term_to_value(operands[0]), False
        else:
            msg = 'One operand must be a field reference'
            raise ast.RegoNodeVisitorError(msg)

        # Симметричные операторы
        if mongo_op in ('$eq', '$ne', '$in'):
            return {field: value} if mongo_op == '$eq' else {field: {mongo_op: value}}

        # Несимметричные операторы
        if direct:
            return {field: {mongo_op: value}}
        inverse = {
            '$lt': '$gt',
            '$lte': '$gte',
            '$gt': '$lt',
            '$gte': '$lte',
        }
        if mongo_op in inverse:
            return {field: {inverse[mongo_op]: value}}
        msg = f'Operator {mongo_op} not supported for reversed operands'
        raise ast.RegoNodeVisitorError(msg)

    def generic_visit(self, node: ast.RegoASTNode) -> Any:
        """Change Generic visit."""
        msg = f'Node of type {type(node).__name__} is not supported'
        raise ast.RegoNodeVisitorError(msg)
