import json
from typing import Any, TypeAlias, Union


class RegoNodeVisitorError(Exception):
    pass


class RegoASTNode:
    """Base class for all Rego AST nodes."""


class QuerySet(RegoASTNode):
    def __init__(self, queries: list['Query']) -> None:
        self.queries = queries

    @classmethod
    def from_data(cls, data: list[list[dict[str, Any]]]) -> 'QuerySet':
        return cls([Query.from_data(q) for q in data])

    def __str__(self) -> str:
        return (
            self.__class__.__name__
            + '('
            + ', '.join(q.__class__.__name__ + '(' + str(q) + ')' for q in self.queries)
            + ')'
        )

    def preprocess(self) -> None:
        for q in self.queries:
            q.preprocess()


class Query(RegoASTNode):
    def __init__(self, exprs: list['Expr']) -> None:
        self.exprs = exprs

    @classmethod
    def from_data(cls, data: list[dict[str, Any]]) -> 'Query':
        return cls([Expr.from_data(e) for e in data])

    def __str__(self) -> str:
        return '; '.join(str(e) for e in self.exprs)

    def preprocess(self) -> None:
        table_names: list[dict[str, str]] = [{}]
        table_vars: dict[str, Any] = {}

        for expr in self.exprs:
            expr._preprocess(table_names, table_vars)


class Expr(RegoASTNode):
    def __init__(self, terms: Union['Term', list['Term']]) -> None:
        self.terms = terms
        self.ignore: bool

    @property
    def operator(self) -> 'Term':
        # if not self.is_call():
        if isinstance(self.terms, Term):
            msg = 'Not a call expr'
            raise ValueError(msg)
        return self.terms[0]

    @property
    def operands(self) -> list['Term']:
        if isinstance(self.terms, Term):
            msg = 'Not a call expr'
            raise ValueError(msg)
        return self.terms[1:]

    def is_call(self) -> bool:
        return not isinstance(self.terms, Term)

    def op(self) -> str:
        return '.'.join([str(t.value.value) for t in self.operator.value.terms])

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> 'Expr':
        terms = data['terms']
        if isinstance(terms, dict):
            return cls(Term.from_data(terms))
        return cls([Term.from_data(t) for t in terms])

    def __str__(self) -> str:
        if not isinstance(self.terms, Term):
            return str(self.operator) + '(' + ', '.join(str(o) for o in self.operands) + ')'
        return str(self.terms)

    def _preprocess(self, table_names: list[dict[str, str]], table_vars: dict[str, Any]) -> None:
        self.ignore = False
        if self.is_call():
            if self.op() == 'eq':
                all_variables: bool = True
                for o in self.operands:
                    if not isinstance(o.value, Ref):
                        all_variables = False
                    else:
                        if isinstance(o.value.operand(-1).value, Scalar):
                            all_variables = False
                        if (
                            isinstance(o.value.operand(-1).value, Var)
                            and '__local' not in o.value.operand(-1).value.value
                        ):
                            all_variables = False
                if all_variables:
                    self.ignore = True
                    return
            for o in self.operands:
                o._preprocess(table_names, table_vars)
        elif isinstance(self.terms, Term):
            self.terms._preprocess(table_names, table_vars)


class Term(RegoASTNode):
    def __init__(self, value: Any) -> None:
        self.value = value

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> 'Term':
        value: Any = None if data['type'] == 'null' else data['value']
        return cls(_VALUE_MAP[data['type']].from_data(value))

    def __str__(self) -> str:
        return str(self.value)

    def _preprocess(self, table_names: list[dict[str, str]], table_vars: dict[str, Any]) -> None:
        if hasattr(self.value, '_preprocess'):
            self.value._preprocess(table_names, table_vars)


class Scalar(RegoASTNode):
    def __init__(self, value: Any) -> None:
        self.value = value

    @classmethod
    def from_data(cls, data: Any) -> 'Scalar':
        return cls(data)

    def __str__(self) -> str:
        return json.dumps(self.value)


class Var(RegoASTNode):
    def __init__(self, value: str) -> None:
        self.value = value

    @classmethod
    def from_data(cls, data: str) -> 'Var':
        return cls(data)

    def __str__(self) -> str:
        return str(self.value)


class Ref(RegoASTNode):
    def __init__(self, terms: list['Term']) -> None:
        self.terms = terms

    def operand(self, idx: int) -> 'Term':
        return self.terms[idx]

    @classmethod
    def from_data(cls, data: list[dict[str, Any]]) -> 'Ref':
        return cls([Term.from_data(x) for x in data])

    def __str__(self) -> str:
        return str(self.terms[0]) + ''.join('[' + str(t) + ']' for t in self.terms[1:])

    def _preprocess(self, table_names: list[dict[str, str]], table_vars: dict[str, Any]) -> None:
        head = self.terms[0].value.value
        if head in table_vars:
            self.terms = table_vars[head] + self.terms[1:]
            return
        row_id = self.terms[2].value
        if not isinstance(row_id, Var):
            msg = f'invalid reference: row identifier type not supported: {row_id.__class__.__name__}'
            raise RegoNodeVisitorError(msg)
        prefix = self.terms[:2]
        table_vars[row_id.value] = prefix
        table_name = self.terms[1].value.value
        exist = table_names[-1].get(table_name, row_id.value)
        if exist != row_id.value:
            msg = 'invalid reference: self-joins not supported'
            raise RegoNodeVisitorError(msg)
        table_names[-1][table_name] = row_id.value
        self.terms = prefix + self.terms[3:]
        # Препроцессинг вложенных терминов
        for t in self.terms:
            t._preprocess(table_names, table_vars)


class Array(RegoASTNode):
    def __init__(self, terms: list['Term']) -> None:
        self.terms = terms

    @classmethod
    def from_data(cls, data: list[dict[str, Any]]) -> 'Array':
        return cls([Term.from_data(x) for x in data])

    def __str__(self) -> str:
        return '[' + ','.join(str(x) for x in self.terms) + ']'

    def _preprocess(self, table_names: list[dict[str, str]], table_vars: dict[str, Any]) -> None:
        for t in self.terms:
            t._preprocess(table_names, table_vars)


class Set(Array):
    pass


class Object(RegoASTNode):
    def __init__(self, *pairs: tuple['Term', 'Term']) -> None:
        self.pairs = pairs

    @classmethod
    def from_data(cls, data: list[tuple[dict[str, Any], dict[str, Any]]]) -> 'Object':
        return cls(*[(Term.from_data(p[0]), Term.from_data(p[1])) for p in data])

    def __str__(self) -> str:
        return '{' + ','.join({str(x): str(y) for (x, y) in self.pairs}) + '}'


class Call(RegoASTNode):
    def __init__(self, terms: list['Term']) -> None:
        self.terms = terms

    @classmethod
    def from_data(cls, data: list[dict[str, Any]]) -> 'Call':
        return cls([Term.from_data(x) for x in data])

    @property
    def operator(self) -> 'Term':
        return self.terms[0]

    @property
    def operands(self) -> list['Term']:
        return self.terms[1:]

    def op(self) -> str:
        return '.'.join([str(t.value.value) for t in self.operator.value.terms])

    def __str__(self) -> str:
        return str(self.operator) + '(' + ', '.join(str(o) for o in self.operands) + ')'

    def _preprocess(self, table_names: list[dict[str, str]], table_vars: dict[str, Any]) -> None:
        for t in self.terms:
            t._preprocess(table_names, table_vars)


class ArrayComprehension(RegoASTNode):
    def __init__(self, term: 'Term', body: 'Query') -> None:
        self.term = term
        self.body = body

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> 'ArrayComprehension':
        return cls(Term.from_data(data['term']), Query.from_data(data['body']))

    def __str__(self) -> str:
        return '[' + str(self.term) + ' | ' + str(self.body) + ']'


class SetComprehension(RegoASTNode):
    def __init__(self, term: 'Term', body: 'Query') -> None:
        self.term = term
        self.body = body

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> 'SetComprehension':
        return cls(Term.from_data(data['term']), Query.from_data(data['body']))

    def __str__(self) -> str:
        return '{' + str(self.term) + ' | ' + str(self.body) + '}'


class ObjectComprehension(RegoASTNode):
    def __init__(self, key: 'Term', value: 'Term', body: 'Query') -> None:
        self.key = key
        self.value = value
        self.body = body

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> 'ObjectComprehension':
        return cls(
            Term.from_data(data['key']),
            Term.from_data(data['value']),
            Query.from_data(data['body']),
        )

    def __str__(self) -> str:
        return '{' + str(self.key) + ':' + str(self.value) + ' | ' + str(self.body) + '}'


def is_comprehension(x: Any) -> bool:
    """Returns true if this is a comprehension type."""
    return isinstance(x, ObjectComprehension | SetComprehension | ArrayComprehension)


ValType: TypeAlias = type[
    Scalar | Var | Ref | Array | Set | Object | Call | ObjectComprehension | SetComprehension | ArrayComprehension
]
_VALUE_MAP: dict[str, ValType] = {
    'null': Scalar,
    'boolean': Scalar,
    'number': Scalar,
    'string': Scalar,
    'var': Var,
    'ref': Ref,
    'array': Array,
    'set': Set,
    'object': Object,
    'call': Call,
    'objectcomprehension': ObjectComprehension,
    'setcomprehension': SetComprehension,
    'arraycomprehension': ArrayComprehension,
}


class RegoNodeVisitor:
    """
    Base class for Rego AST visitors.
    """

    def visit(self, node: RegoASTNode) -> Any:
        method = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: RegoASTNode) -> None:
        for attr in dir(node):
            if not attr.startswith('_'):
                value = getattr(node, attr)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, RegoASTNode):
                            self.visit(item)
                elif isinstance(value, RegoASTNode):
                    self.visit(value)

    def _is_field_ref(self, term: Term) -> bool:
        v = term.value
        return isinstance(v, Ref) and len(v.terms) >= 3

    def _term_to_field(self, term: Term) -> Any:
        v = term.value
        if isinstance(v, Ref) and len(v.terms) >= 3:
            return v.terms[2].value.value
        msg = 'Operand must be a field reference'
        raise RegoNodeVisitorError(msg)

    def _term_to_value(self, term: Term) -> Any:
        v = term.value
        if isinstance(v, Scalar):
            return v.value
        elif isinstance(v, Array | Set):
            return [t.value.value for t in v.terms]
        elif isinstance(v, Ref) and len(v.terms) >= 3:
            return v.terms[2].value.value
        msg = 'Unsupported operand type'
        raise RegoNodeVisitorError(msg)
