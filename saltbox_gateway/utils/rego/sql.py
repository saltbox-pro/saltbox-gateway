import json
from collections.abc import Sequence
from typing import Any


class Union:
    def __init__(self, clauses: Sequence['Where | InnerJoin']) -> None:
        self.clauses: Sequence[Where | InnerJoin] = clauses


class InnerJoin:
    def __init__(self, tables: set[str], expr: 'Conjunction') -> None:
        self.tables: set[str] = tables
        self.expr: Conjunction = expr

    def sql(self, **kwargs: Any) -> str:
        return ' '.join(['INNER JOIN ' + t for t in sorted(self.tables)]) + ' ON ' + self.expr.sql(**kwargs)


class Where:
    def __init__(self, expr: 'Disjunction') -> None:
        self.expr: Disjunction = expr

    def sql(self, **kwargs: Any) -> str:
        return 'WHERE ' + self.expr.sql(**kwargs)


class Disjunction:
    def __init__(self, conjunction: Sequence['Conjunction']) -> None:
        self.conjunction: Sequence[Conjunction] = conjunction

    def sql(self, **kwargs: Any) -> str:
        return '(' + ' OR '.join([c.sql(**kwargs) for c in self.conjunction]) + ')'


class Conjunction:
    def __init__(self, relation: Sequence['Relation']) -> None:
        self.relation: Sequence[Relation] = relation

    def sql(self, **kwargs: Any) -> str:
        if len(self.relation) == 0:
            return '1'
        return '(' + ' AND '.join([r.sql(**kwargs) for r in self.relation]) + ')'


class Relation:
    def __init__(
        self, operator: 'RelationOp', lhs: 'Column | Call | Constant | Array', rhs: 'Column | Call | Constant | Array'
    ) -> None:
        self.operator: RelationOp = operator
        self.lhs: Column | Call | Constant | Array = lhs
        self.rhs: Column | Call | Constant | Array = rhs

    def sql(self, **kwargs: Any) -> str:
        return f'{self.lhs.sql(**kwargs)} {self.operator.sql(**kwargs)} {self.rhs.sql(**kwargs)}'


class Column:
    def __init__(self, name: str, table: str = '') -> None:
        self.table: str = table
        self.name: str = name

    def sql(self, **kwargs: Any) -> str:
        if self.table:
            return f'{self.table}.{self.name}'
        return str(self.name)


class Call:
    def __init__(self, operator: str, operands: Sequence['Column | Call | Constant | Array']) -> None:
        self.operator: str = operator
        self.operands: Sequence[Column | Call | Constant | Array] = operands

    def sql(self, **kwargs: Any) -> str:
        return self.operator + '(' + ', '.join(o.sql(**kwargs) for o in self.operands) + ')'


class Constant:
    def __init__(self, value: Any) -> None:
        self.value: Any = value

    def sql(self, **kwargs: Any) -> str:
        if kwargs.get('use_single_quotes', False):
            if isinstance(self.value, str):
                return "'" + self.value + "'"
        return json.dumps(self.value)


class Array:
    def __init__(self, values: Sequence['Constant']) -> None:
        self.values: Sequence[Constant] = values

    def sql(self, **kwargs: Any) -> str:
        return '(' + ', '.join(e.sql(**kwargs) for e in self.values) + ')'


class RelationOp:
    def __init__(self, value: str) -> None:
        self.value: str = value

    def sql(self, **kwargs: Any) -> str:
        return self.value


def build_sql_query(
    select: str,
    from_table: str,
    where: str = '',
    clauses: Union | None = None,
    sql_kwargs: dict | None = None,
) -> str:
    """
    Returns a SQL query as a string constructed from the caller's provided
    values and the SQL AST clauses.
    """
    sql_query = f'SELECT {select} FROM {from_table}'  # noqa: S608
    if clauses is not None and getattr(clauses, 'clauses', None) is not None:
        queries = [sql_query] * len(clauses.clauses)
        for i, clause in enumerate(clauses.clauses):
            if sql_kwargs is None:
                sql_kwargs = {}
            queries[i] = queries[i] + ' ' + clause.sql(**sql_kwargs)
            if where:
                queries[i] = queries[i] + ' AND (' + where + ')'
        return ' UNION '.join(queries)
    return sql_query
