#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from datetime import datetime
from decimal import Decimal

from collections import defaultdict

from ...expr.reduction import *
from ...expr.arithmetic import BinOp, Add, Power, Invert, Negate, Abs
from ...expr.merge import JoinCollectionExpr, UnionCollectionExpr
from ...expr.collections import SortedCollectionExpr
from ...expr.window import CumSum
from ...expr import element
from ...expr import strings
from ...expr import datetimes
from ... import types as df_types
from . import types
from ..core import Backend
from .... import utils
from ..errors import CompileError

GROUPBY_LIMIT = 10000

BINARY_OP_COMPILE_DIC = {
    'Add': '+',
    'Substract': '-',
    'Multiply': '*',
    'Divide': '/',
    'Greater': '>',
    'GreaterEqual': '>=',
    'Less': '<',
    'LessEqual': '<=',
    'Equal': '==',
    'NotEqual': '!=',
    'And': 'and',
    'Or': 'or'
}

UNARY_OP_COMPILE_DIC = {
    'Negate': '-'
}

WINDOW_COMPILE_DIC = {
    'CumSum': 'sum',
    'CumMean': 'avg',
    'CumMedian': 'median',
    'CumStd': 'stddev',
    'CumMax': 'max',
    'CumMin': 'min',
    'CumCount': 'count',
    'Lag': 'lag',
    'Lead': 'lead',
    'Rank': 'rank',
    'DenseRank': 'dense_rank',
    'PercentRank': 'percent_rank',
    'RowNumber': 'row_number'
}

MATH_COMPILE_DIC = {
    'Abs': 'abs',
    'Sqrt': 'sqrt',
    'Sin': 'sin',
    'Sinh': 'sinh',
    'Cos': 'cos',
    'Cosh': 'cosh',
    'Tan': 'tan',
    'Tanh': 'tanh',
    'Exp': 'exp',
    'Arccos': 'acos',
    'Arcsin': 'asin',
    'Arctan': 'atan',
    'Ceil': 'ceil',
    'Floor': 'floor'
}

DATE_PARTS_DIC = {
    'Year': 'yyyy',
    'Month': 'mm',
    'Day': 'dd',
    'Hour': 'hh',
    'Minute': 'mi',
    'Second': 'ss'
}


class OdpsSQLCompiler(Backend):
    def __init__(self, ctx, indent_size=2, beautify=False):
        self._ctx = ctx
        self._indent_size = indent_size
        self._beautify = beautify

        # use for `join` or `union` operations etc.
        self._sub_compiles = defaultdict(lambda: list())
        # When encountering `join` or `union`, we will try to compile all child branches,
        # for each nodes of these branches, we should not check the uniqueness,
        # when compilation finishes, we substitute the children of `join` or `union` with None,
        # so the upcoming compilation will not visit its children.
        # When everything are done, we use the callbacks to substitute back the original children
        # of the `join` or `union` node.
        self._callbacks = list()

        self._re_init()

    def _re_init(self):
        self._select_clause = None
        self._from_clause = None
        self._where_clause = None
        self._group_by_clause = None
        self._having_clause = None
        self._order_by_clause = None
        self._limit = None
        self._join_predicates = None

    def _cleanup(self):
        self._sub_compiles = dict()
        for callback in self._callbacks:
            callback()
        self._callbacks = list()

    @classmethod
    def _need_recursive_handle_in_expr(cls, node):
        return isinstance(node, (element.IsIn, element.NotIn)) and \
               not all(n is None for n in node.args) and \
               isinstance(node.values[0], SequenceExpr)

    @classmethod
    def _retrieve_until_find_root(cls, expr):
        for node in expr.traverse(top_down=True, unique=True):
            if isinstance(node, (JoinCollectionExpr, UnionCollectionExpr)) and \
                    not all(n is None for n in node.args):
                yield node
            else:
                ins = [n for n in node.children() if cls._need_recursive_handle_in_expr(n)]
                if len(ins) > 0:
                    for n in ins:
                        yield n

    @classmethod
    def _is_source_table(cls, expr):
        if isinstance(expr, CollectionExpr) and expr._source_data is not None:
            return True

        return False

    def _compile_union_node(self, expr, traversed):
        compiled = self._compile(expr.lhs)

        self._sub_compiles[expr].append(compiled)

        compiled = self._compile(expr.rhs)
        self._sub_compiles[expr].append(compiled)

        cached_args = expr.args

        def cb():
            expr._cached_args = cached_args
        self._callbacks.append(cb)

        expr._cached_args = [None] * len(expr.args)

    def _compile_join_node(self, expr, traversed):
        compiled = self._compile(expr.lhs)
        if not self._is_source_table(expr.lhs) and not isinstance(expr.lhs, JoinCollectionExpr):
            self._sub_compiles[expr].append(
                '(\n{0}\n) {1}'.format(utils.indent(compiled, self._indent_size),
                                     self._ctx.get_collection_alias(expr.lhs, True)[0])
            )
        else:
            self._sub_compiles[expr].append(self._ctx.get_expr_compiled(expr.lhs))

        compiled = self._compile(expr.rhs)
        if not self._is_source_table(expr.rhs):
            self._sub_compiles[expr].append(
                '(\n{0}\n) {1}'.format(utils.indent(compiled, self._indent_size),
                                     self._ctx.get_collection_alias(expr.rhs, True)[0])
            )
        else:
            self._sub_compiles[expr].append(self._ctx.get_expr_compiled(expr.rhs))

        self._compile(expr.predicate, traversed)
        self._sub_compiles[expr].append(self._ctx.get_expr_compiled(expr.predicate))

        cached_args = expr.args

        def cb():
            expr._cached_args = cached_args
        self._callbacks.append(cb)

        expr._cached_args = [None] * len(expr.args)

    @classmethod
    def _find_table(cls, expr):
        return next(it for it in expr.traverse(top_down=True, unique=True)
                    if isinstance(it, CollectionExpr))

    def _compile_in_node(self, expr, traversed):
        self._compile(expr.input)
        self._sub_compiles[expr].append(self._ctx.get_expr_compiled(expr.input))

        to_sub = self._find_table(expr.values[0])[[expr.values[0], ]]
        compiled = self._compile(to_sub)
        self._sub_compiles[expr].append(compiled)

        cached_args = expr.values

        def cb():
            expr._cached_args = cached_args
        self._callbacks.append(cb)

        expr._cached_args = [None] * len(expr.args)

    def _compile(self, expr, traversed=None):
        roots = self._retrieve_until_find_root(expr)

        if traversed is None:
            traversed = set()

        for root in roots:
            if root is not None:
                if isinstance(root, JoinCollectionExpr):
                    self._compile_join_node(root, traversed)
                elif isinstance(root, UnionCollectionExpr):
                    self._compile_union_node(root, traversed)
                elif isinstance(root, (element.IsIn, element.NotIn)):
                    self._compile_in_node(root, traversed)
                root.accept(self)
                traversed.add(id(root))

        for node in expr.traverse():
            if id(node) not in traversed:
                node.accept(self)
                traversed.add(id(node))

        return self.to_sql().strip()

    def compile(self, expr):
        try:
            return self._compile(expr)
        finally:
            self._cleanup()

    def to_sql(self):
        lines = [
            'SELECT {0} '.format(self._select_clause or '*'),
            'FROM {0} '.format(self._from_clause),
        ]

        if self._join_predicates:
            lines.append('ON {0}'.format(self._join_predicates))
        if self._where_clause:
            lines.append('WHERE {0} '.format(self._where_clause))
        if self._group_by_clause:
            lines.append('GROUP BY {0} '.format(self._group_by_clause))
            if self._having_clause:
                lines.append('HAVING {0} '.format(self._having_clause))
        if self._order_by_clause:
            if not self._limit:
                self._limit = GROUPBY_LIMIT
            lines.append('ORDER BY {0} '.format(self._order_by_clause))
        if self._limit is not None:
            lines.append('LIMIT {0}'.format(self._limit))

        self._re_init()
        return '\n'.join(lines)

    def sub_sql_to_from_clause(self, expr):
        sql = self.to_sql()

        while True:
            # lift the collection to fit the analyzer's column-lifting
            if isinstance(expr, (SliceCollectionExpr, SortedCollectionExpr,
                                 FilterCollectionExpr)):
                expr = expr.input
                continue
            else:
                break

        alias, _ = self._ctx.get_collection_alias(expr, create=True)
        from_clause = '(\n{0}\n) {1}'.format(
            utils.indent(sql, self._indent_size), alias
        )

        self._re_init()
        self._from_clause = from_clause

    def add_select_clause(self, expr, select_clause):
        if self._select_clause is not None:
            self.sub_sql_to_from_clause(expr.input)

        self._select_clause = select_clause

    def add_from_clause(self, expr, from_clause):
        if self._from_clause is None:
            self._from_clause = from_clause

    def add_where_clause(self, expr, where_clause):
        if self._where_clause is not None:
            self.sub_sql_to_from_clause(expr)

        self._where_clause = where_clause

    def add_group_by_clause(self, expr, group_by_clause):
        if self._group_by_clause is not None:
            self.sub_sql_to_from_clause(expr)

        self._group_by_clause = group_by_clause

    def add_having_clause(self, expr, having_clause):
        if self._having_clause is None:
            self._having_clause = having_clause

        assert having_clause == self._having_clause

    def add_order_by_clause(self, expr, order_by_clause):
        if self._order_by_clause is not None:
            self.sub_sql_to_from_clause(expr)

        self._order_by_clause = order_by_clause

    def set_limit(self, limit):
        self._limit = limit

    def visit_source_collection(self, expr):
        alias = self._ctx.register_collection(expr)

        source_data = expr._source_data
        name = '%s.`%s`' % (source_data.project.name, source_data.name)

        from_clause = '{0} {1}'.format(name, alias)
        self.add_from_clause(expr, from_clause)
        self._ctx.add_expr_compiled(expr, from_clause)

    def _compile_select_field(self, field):
        compiled = self._ctx.get_expr_compiled(field)

        if not isinstance(field, Column):
            compiled = '{0} AS {1}'.format(compiled, field.name)
        elif field.name is not None and field._name is None:
            compiled = '{0} AS {1}'.format(compiled, field.name)
        elif field.name is not None and field.source_name is not None and field.name != field.source_name:
            compiled = '{0} AS {1}'.format(compiled, field.name)

        return compiled

    def _compile_select_collection(self, collection):
        compiled, _ = self._ctx.get_collection_alias(collection, create=True)

        return '{0}.*'.format(compiled)

    def _join_compiled_fields(self, fields):
        if not self._beautify:
            return ', '.join(fields)
        else:
            buf = six.StringIO()
            buf.write('\n')

            split_fields = [field.rsplit(' AS ', 1) for field in fields]
            get = lambda s: s if '\n' not in s else s.rsplit('\n', 1)[1]
            max_length = max(len(get(f[0])) for f in split_fields)

            for f in split_fields:
                if len(f) > 1:
                    buf.write(f[0].ljust(max_length))
                    buf.write(' AS ')
                    buf.write(f[1])
                else:
                    buf.write(f[0])
                buf.write(',\n')

            return utils.indent(buf.getvalue()[:-2], self._indent_size)

    def visit_project_collection(self, expr):
        fields = expr.children()[1:]
        compiled_fields = [self._compile_select_field(field)
                           for field in fields]

        compiled = self._join_compiled_fields(compiled_fields)

        self._ctx.add_expr_compiled(expr, compiled)
        self.add_select_clause(expr, compiled)

    def visit_filter_collection(self, expr):
        predicate = expr.args[1]
        compiled = self._ctx.get_expr_compiled(predicate)

        if self._group_by_clause is not None or \
                isinstance(expr.input, ProjectCollectionExpr):
            self.sub_sql_to_from_clause(expr.input)

        self._ctx.add_expr_compiled(expr, compiled)
        self.add_where_clause(expr, compiled)

    def visit_slice_collection(self, expr):
        sliced = expr._indexes
        if sliced[0] is not None:
            raise NotImplementedError
        if sliced[2] is not None:
            raise NotImplementedError

        self.set_limit(sliced[1].value)

    def visit_element_op(self, expr):
        if isinstance(expr, element.IsNull):
            compiled = '{0} IS NULL'.format(
                self._ctx.get_expr_compiled(expr.input))
        elif isinstance(expr, element.NotNull):
            compiled = '{0} IS NOT NULL'.format(
                self._ctx.get_expr_compiled(expr.input))
        elif isinstance(expr, element.FillNa):
            compiled = 'IF(%(input)s IS NULL, %(value)r, %(input)s)' % {
                'input': self._ctx.get_expr_compiled(expr.input),
                'value': expr.value
            }
        elif isinstance(expr, element.IsIn):
            if expr.values is not None:
                compiled = '{0} IN ({1})'.format(
                    self._ctx.get_expr_compiled(expr.input),
                    ', '.join(self._ctx.get_expr_compiled(it) for it in expr.values)
                )
            else:
                subs = self._sub_compiles[expr]
                compiled = '{0} IN ({1})'.format(
                    subs[0], subs[1].replace('\n', '')
                )
        elif isinstance(expr, element.NotIn):
            if expr.values is not None:
                compiled = '{0} NOT IN ({1})'.format(
                    self._ctx.get_expr_compiled(expr.input),
                    ', '.join(self._ctx.get_expr_compiled(it) for it in expr.values)
                )
            else:
                subs = self._sub_compiles[expr]
                compiled = '{0} NOT IN ({1})'.format(
                    subs[0], subs[1].replace('\n', '')
                )
        elif isinstance(expr, element.IfElse):
            compiled = 'IF({0}, {1}, {2})'.format(
                self._ctx.get_expr_compiled(expr._input),
                self._ctx.get_expr_compiled(expr._then),
                self._ctx.get_expr_compiled(expr._else),
            )
        elif isinstance(expr, element.Switch):
            case = self._ctx.get_expr_compiled(expr.case) + ' ' \
                if expr.case is not None else ''
            lines = ['CASE {0}'.format(case)]
            for pair in zip(expr.conditions, expr.thens):
                args = [self._ctx.get_expr_compiled(p) for p in pair]
                lines.append('WHEN {0} THEN {1} '.format(*args))
            if expr.default is not None:
                lines.append('ELSE {0} '.format(self._ctx.get_expr_compiled(expr.default)))
            lines.append('END')
            if self._beautify:
                for i in range(1, len(lines) - 1):
                    lines[i] = utils.indent(lines[i], self._indent_size)
                compiled = '\n'.join(lines)
            else:
                compiled = ''.join(lines)
        else:
            raise NotImplementedError

        self._ctx.add_expr_compiled(expr, compiled)

    def _parenthesis(self, child):
        if isinstance(child, BinOp):
            return '(%s)' % self._ctx.get_expr_compiled(child)
        elif isinstance(child, (element.IsNull, element.NotNull, element.IsIn, element.NotIn,
                                element.Between, element.Switch, element.Cut)):
            return '(%s)' % self._ctx.get_expr_compiled(child)
        else:
            return self._ctx.get_expr_compiled(child)

    def visit_binary_op(self, expr):
        if isinstance(expr, Add) and expr.dtype == df_types.string:
            compiled = 'CONCAT({0}, {1})'.format(
                self._ctx.get_expr_compiled(expr.lhs),
                self._ctx.get_expr_compiled(expr.rhs),
            )
        else:
            compiled, op = None, None
            try:
                op = BINARY_OP_COMPILE_DIC[expr.node_name].upper()
            except KeyError:
                if isinstance(expr, Power):
                    compiled = 'POW({0}, {1})'.format(
                        self._ctx.get_expr_compiled(expr.lhs),
                        self._ctx.get_expr_compiled(expr.rhs)
                    )
                    if not isinstance(expr.dtype, df_types.Float):
                        compiled = self._cast(compiled, df_types.float64, expr.dtype)
                else:
                    raise NotImplementedError

            if compiled is None:
                lhs, rhs = expr.args
                if op:
                    compiled = '{0} {1} {2}'.format(
                        self._parenthesis(lhs), op, self._parenthesis(rhs)
                    )
                else:
                    raise NotImplementedError

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_unary_op(self, expr):
        try:
            if isinstance(expr, Negate) and expr.input.dtype == df_types.boolean:
                compiled = 'NOT {0}'.format(self._parenthesis(expr.input))
            else:
                op = UNARY_OP_COMPILE_DIC[expr.node_name]

                compiled = '{0}{1}'.format(
                        op, self._parenthesis(expr.input))
        except KeyError:
            if isinstance(expr, Abs):
                compiled = 'ABS({0})'.format(
                    self._ctx.get_expr_compiled(expr.input))
            elif isinstance(expr, (Invert, Negate)) and \
                    expr.input.dtype == df_types.boolean:
                compiled = 'NOT {0}'.format(self._parenthesis(expr.input))
            else:
                raise NotImplementedError

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_math(self, expr):
        compiled = None
        try:
            op = MATH_COMPILE_DIC[expr.node_name]
        except KeyError:
            if expr.node_name == 'Log':
                if expr._base is None:
                    op = 'ln'
                else:
                    compiled = 'LOG({0}, {1})'.format(
                        self._ctx.get_expr_compiled(expr._base),
                        self._ctx.get_expr_compiled(expr.input)
                    )
            elif expr.node_name == 'Log2':
                compiled = 'LOG(2, {0})'.format(
                    self._ctx.get_expr_compiled(expr.input)
                )
            elif expr.node_name == 'Log10':
                compiled = 'LOG(10, {0})'.format(
                    self._ctx.get_expr_compiled(expr.input)
                )
            elif expr.node_name == 'Log1p':
                compiled = 'LN(1 + {0})'.format(
                    self._ctx.get_expr_compiled(expr.input)
                )
            elif expr.node_name == 'Expm1':
                compiled = 'EXP({0}) - 1'.format(
                    self._ctx.get_expr_compiled(expr.input)
                )
            elif expr.node_name == 'Trunc':
                if expr._decimals is None:
                    op = 'trunc'
                else:
                    compiled = 'TRUNC({0}, {1})'.format(
                        self._ctx.get_expr_compiled(expr.input),
                        self._ctx.get_expr_compiled(expr._decimals)
                    )
            else:
                raise NotImplementedError

        if compiled is None:
            compiled = '{0}({1})'.format(
                op.upper(), self._ctx.get_expr_compiled(expr.input))

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_string_op(self, expr):
        # FIXME quite a few operations cannot support by internal function
        compiled = None

        input = self._ctx.get_expr_compiled(expr.input)
        if isinstance(expr, strings.Capitalize):
            compiled = 'CONCAT(TOUPPER(SUBSTR(%(input)s, 1, 1)), TOLOWER(SUBSTR(%(input)s, 2)))' % {
                'input': input
            }
        elif isinstance(expr, strings.Contains):
            if not expr.case or expr.flags > 0:
                raise NotImplementedError
            func = 'INSTR' if not expr.regex else 'REGEXP_INSTR'
            compiled = '%s(%s, %s) > 0' % (func, input, self._ctx.get_expr_compiled(expr._pat))
        elif isinstance(expr, strings.Count):
            compiled = 'REGEXP_COUNT(%s, %s)' % (input, self._ctx.get_expr_compiled(expr._pat))
        elif isinstance(expr, strings.Endswith):
            # TODO: any better solution?
            compiled = 'INSTR(REVERSE(%s), REVERSE(%s)) == 1' % (
                input, self._ctx.get_expr_compiled(expr._pat))
        elif isinstance(expr, strings.Startswith):
            compiled = 'INSTR(%s, %s) == 1' % (input, self._ctx.get_expr_compiled(expr._pat))
        elif isinstance(expr, strings.Extract):
            if expr.flags > 0:
                raise NotImplementedError
            group = self._ctx.get_expr_compiled(expr._group) if expr.group is not None else 0
            compiled = 'REGEXP_EXTRACT(%s, %s, %s)' % (
                input, self._ctx.get_expr_compiled(expr._pat), group)
        elif isinstance(expr, strings.Find):
            if isinstance(expr.start, six.integer_types):
                start = expr.start + 1 if expr.start >= 0 else expr.start
            else:
                start = 'IF(%(start)s >= 0, %(start)s + 1, %(start)s)' % {
                    'start': self._ctx.get_expr_compiled(expr._start)
                }
            if expr.end is not None:
                raise NotImplementedError
            else:
                compiled = 'INSTR(%s, %s, %s) - 1' % (
                    input, self._ctx.get_expr_compiled(expr._sub), start)
        elif isinstance(expr, strings.Replace):
            if not expr.case or expr.flags > 0:
                raise NotImplementedError
            compiled = 'REGEXP_REPLACE(%s, %s, %s, %s)' % (
                input, self._ctx.get_expr_compiled(expr._pat),
                self._ctx.get_expr_compiled(expr._repl), 0 if expr.n < 0 else expr.n)
        elif isinstance(expr, strings.Get):
            compiled = 'SUBSTR(%s, %s, 1)' % (input, expr.index + 1)
        elif isinstance(expr, strings.Len):
            compiled = 'LENGTH(%s)' % input
        elif isinstance(expr, strings.Lower):
            compiled = 'TOLOWER(%s)' % input
        elif isinstance(expr, strings.Upper):
            compiled = 'TOUPPER(%s)' % input
        elif isinstance(expr, (strings.Lstrip, strings.Rstrip, strings.Strip)):
            if expr.to_strip != ' ':
                raise NotImplementedError
            func = {
                'Lstrip': 'LTRIM',
                'Rstrip': 'RTRIM',
                'Strip': 'TRIM'
            }
            compiled = '%s(%s)' % (func[type(expr).__name__], input)
        elif isinstance(expr, strings.Repeat):
            compiled = 'REPEAT(%s, %s)' % (
                input, self._ctx.get_expr_compiled(expr._repeats))
        elif isinstance(expr, strings.Substr):
            if expr.length is not None:
                compiled = 'SUBSTR(%s, %s, %s)' % (
                    input, self._ctx.get_expr_compiled(expr._start),
                    self._ctx.get_expr_compiled(expr._length))
            else:
                compiled = 'SUBSTR(%s, %s)' % (
                    input, self._ctx.get_expr_compiled(expr._start))

        if compiled is not None:
            self._ctx.add_expr_compiled(expr, compiled)
        else:
            raise NotImplementedError

    def visit_datetime_op(self, expr):
        # FIXME quite a few operations cannot support by internal function
        class_name = type(expr).__name__
        input = self._ctx.get_expr_compiled(expr.input)

        compiled = None
        if class_name in DATE_PARTS_DIC:
            compiled = 'DATEPART(%s, %r)' % (input, DATE_PARTS_DIC[class_name])
        elif isinstance(expr, datetimes.WeekOfYear):
            compiled = 'WEEKOFYEAR(%s)' % input
        elif isinstance(expr, datetimes.WeekDay):
            compiled = 'WEEKDAY(%s)' % input

        if compiled is not None:
            self._ctx.add_expr_compiled(expr, compiled)
        else:
            raise NotImplementedError

    def visit_groupby(self, expr):
        bys, having, aggs, fields = tuple(expr.args[1:])
        if fields is None:
            fields = bys + aggs

        by_fields = [self._ctx.get_expr_compiled(by) for by in bys]
        group_by_clause = self._join_compiled_fields(by_fields)

        select_fields = [self._compile_select_field(field) for field in fields]
        select_clause = self._join_compiled_fields(select_fields)

        self.add_select_clause(expr, select_clause)
        self.add_group_by_clause(expr, group_by_clause)

        if having:
            self.add_having_clause(expr, self._ctx.get_expr_compiled(having))

    def visit_mutate(self, expr):
        bys, mutates = tuple(expr.args[1:])

        select_fields = [self._compile_select_field(field) for field in bys + mutates]
        select_clause = self._join_compiled_fields(select_fields)

        self.add_select_clause(expr, select_clause)

    def _compile_sort_expr(self, field):
        get_field = lambda field: self._ctx.get_expr_compiled(field)
        return '{0} DESC'.format(get_field(field)) \
            if not field._ascending else get_field(field)

    def visit_sort(self, expr):
        keys_fields = expr.args[1]

        order_by_clause = self._join_compiled_fields(
            [self._compile_sort_expr(field) for field in keys_fields])

        self.add_order_by_clause(expr, order_by_clause)

    def visit_distinct(self, expr):
        distinct_fields = expr.args[1]

        fields_clause = self._join_compiled_fields(
            [self._compile_select_field(field) for field in distinct_fields])
        select_clause = 'DISTINCT {0}'.format(fields_clause)

        self.add_select_clause(expr, select_clause)

    def visit_reduction(self, expr):
        if isinstance(expr, (Count, GroupedCount)) and isinstance(expr.input, CollectionExpr):
            compiled = 'COUNT(1)'
            self._ctx.add_expr_compiled(expr, compiled)
            return

        if isinstance(expr, (Var, GroupedVar, Std, GroupedStd)):
            if expr._ddof != 0:
                raise CompileError('Does not support %s with ddof=%s' % (
                    expr.node_name, expr._ddof))

        compiled = None

        if isinstance(expr, (Mean, GroupedMean)):
            node_name = 'avg'
        elif isinstance(expr, (Std, GroupedStd)):
            node_name = 'stddev'
        elif isinstance(expr, (Sum, GroupedSum)) and expr.input.dtype == df_types.string:
            compiled = 'WM_CONCAT(\'\', %s)' % self._ctx.get_expr_compiled(expr.input)
        elif isinstance(expr, (Sum, GroupedSum)) and expr.input.dtype == df_types.boolean:
            compiled = 'SUM(IF(%s, 1, 0))' % self._ctx.get_expr_compiled(expr.input)
        elif isinstance(expr, (Max, GroupedMax, Min, GroupedMin)) and \
                expr.input.dtype == df_types.boolean:
            compiled = '%s(IF(%s, 1, 0)) == 1' % (
                expr.node_name, self._ctx.get_expr_compiled(expr.input))
        elif isinstance(expr, (Any, GroupedAny)):
            compiled = 'MAX(IF(%s, 1, 0)) == 1' % self._ctx.get_expr_compiled(expr.args[0])
        elif isinstance(expr, (All, GroupedAll)):
            compiled = 'MIN(IF(%s, 1, 0)) == 1' % self._ctx.get_expr_compiled(expr.args[0])
        else:
            node_name = expr.node_name

        if compiled is None:
            compiled = '{0}({1})'.format(
                node_name.upper(), self._ctx.get_expr_compiled(expr.args[0]))

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_column(self, expr):
        collection = expr.input

        alias, _ = self._ctx.get_collection_alias(collection, create=True)

        compiled = '{0}.`{1}`'.format(alias, expr.source_name)
        self._ctx.add_expr_compiled(expr, compiled)

    def visit_map(self, expr):
        func_name = self._ctx.get_udf(expr._func)

        compiled = '{0}({1})'.format(func_name, self._ctx.get_expr_compiled(expr.input))

        self._ctx.add_expr_compiled(expr, compiled)

    def _wrap_typed(self, expr, compiled):
        if expr._source_data_type != expr._data_type:
            compiled = 'cast({0} AS {1})'.format(
                compiled, types.df_type_to_odps_type(expr._data_type))

        return compiled

    def visit_sequence(self, expr):
        compiled = expr._source_name
        compiled = self._wrap_typed(expr, compiled)

        self._ctx.add_expr_compiled(expr, compiled)

    def _compile_window_function(self, func, args, partition_by=None,
                                 order_by=None, preceding=None, following=None):
        partition_by = 'PARTITION BY {0}'.format(partition_by or '1')
        order_by = 'ORDER BY {0}'.format(order_by) if order_by is not None else ''

        if isinstance(preceding, tuple):
            window_clause = 'ROWS BETWEEN {0} PRECEDING AND {1} PRECEDING' \
                .format(*preceding)
        elif isinstance(following, tuple):
            window_clause = 'ROWS BETWEEN {0} FOLLOWING AND {1} FOLLOWING' \
                .format(*following)
        elif preceding is not None and following is not None:
            window_clause = 'ROWS BETWEEN {0} PRECEDING AND {1} FOLLOWING' \
                .format(preceding, following)
        elif preceding is not None:
            window_clause = 'ROWS {0} PRECEDING'.format(preceding)
        elif following is not None:
            window_clause = 'ROWS {0} FOLLOWING'.format(following)
        else:
            window_clause = ''

        over = ' '.join(sub for sub in (partition_by, order_by, window_clause)
                        if len(sub) > 0)

        return '{0}({1}) OVER ({2})'.format(func, args, over)

    def visit_cum_window(self, expr):
        col_compiled = self._ctx.get_expr_compiled(expr.input)
        if isinstance(expr, CumSum) and expr.input.dtype == df_types.boolean:
            col_compiled = 'IF({0}, 1, 0)'.format(col_compiled)
        if expr.distinct:
            col_compiled = 'DISTINCT {0}'.format(col_compiled)

        partition_by = ', '.join(self._ctx.get_expr_compiled(by)
                                 for by in expr._partition_by) if expr._partition_by else None
        order_by = ', '.join(self._compile_sort_expr(by)
                             for by in expr._order_by) if expr._order_by else None

        func_name = WINDOW_COMPILE_DIC[expr.node_name].upper()
        compiled = self._compile_window_function(func_name, col_compiled, partition_by=partition_by,
                                                 order_by=order_by, preceding=expr._preceding,
                                                 following=expr._following)

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_rank_window(self, expr):
        func_name = WINDOW_COMPILE_DIC[expr.node_name].upper()

        partition_by = ', '.join(self._ctx.get_expr_compiled(by)
                                 for by in expr._partition_by) if expr._partition_by else None
        order_by = ', '.join(self._compile_sort_expr(by)
                             for by in expr._order_by) if expr._order_by else None

        compiled = self._compile_window_function(func_name, '', partition_by=partition_by,
                                                 order_by=order_by)

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_shift_window(self, expr):
        func_name = WINDOW_COMPILE_DIC[expr.node_name].upper()

        compiled_fields = [self._ctx.get_expr_compiled(expr.input), ]
        if expr._offset:
            compiled_fields.append((expr._offset))
        if expr._default:
            compiled_fields.append(str(expr._default))

        col_compiled = self._join_compiled_fields(compiled_fields)

        partition_by = ', '.join(self._ctx.get_expr_compiled(by)
                                 for by in expr._partition_by) if expr._partition_by else None
        order_by = ', '.join(self._compile_sort_expr(by)
                             for by in expr._order_by) if expr._order_by else None

        compiled = self._compile_window_function(func_name, col_compiled, partition_by=partition_by,
                                                 order_by=order_by)

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_scalar(self, expr):
        compiled = None
        if expr._value is not None:
            if expr.dtype == df_types.string and isinstance(expr.value, six.text_type):
                compiled = repr(utils.to_str(expr.value))
            elif isinstance(expr._value, bool):
                compiled = 'true' if expr._value else 'false'
            elif isinstance(expr._value, datetime):
                # FIXME: just ignore shorter than second
                compiled= 'FROM_UNIXTIME({0})'.format(utils.to_timestamp(expr._value))
            elif isinstance(expr._value, Decimal):
                compiled = 'CAST({0} AS DECIMAL)'.format(repr(str(expr._value)))

        if compiled is None:
            compiled = repr(expr._value)
        self._ctx.add_expr_compiled(expr, compiled)

    @classmethod
    def _cast(cls, compiled, source_type, to_type):
        source_odps_type = types.df_type_to_odps_type(source_type)
        to_type = types.df_type_to_odps_type(to_type)

        if not to_type.can_explicit_cast(source_odps_type):
            raise CompileError(
                    'Cannot cast from %s to %s' % (source_odps_type, to_type))

        return 'CAST({0} AS {1})'.format(compiled, to_type)

    def visit_cast(self, expr):
        compiled = self._ctx.get_expr_compiled(expr._input)

        if isinstance(expr.source_type, df_types.Integer) and expr.dtype == df_types.datetime:
            compiled = 'FROM_UNIXTIME({0})'.format(self._ctx.get_expr_compiled(expr.input))
        elif expr.dtype is not expr.source_type:
            compiled = self._cast(compiled, expr.source_type, expr.dtype)

        self._ctx.add_expr_compiled(expr, compiled)

    def visit_join(self, expr):
        left_compiled, right_compiled, predicate_compiled = tuple(self._sub_compiles[expr])

        from_clause = '{0} \n{1} JOIN \n{2}'.format(
            left_compiled, expr._how, utils.indent(right_compiled, self._indent_size)
        )

        from_clause += '\nON {0}'.format(predicate_compiled)

        self.add_from_clause(expr, from_clause)
        self._ctx.add_expr_compiled(expr, from_clause)

    def visit_union(self, expr):
        if expr._distinct:
            raise CompileError("Distinct union is not supported here.")

        left_compiled, right_compiled = tuple(self._sub_compiles[expr])

        from_clause = '{0} \nUNION ALL\n{1}'.format(left_compiled, utils.indent(right_compiled, self._indent_size))

        compiled = '(\n{0}\n) {1}'.format(utils.indent(from_clause, self._indent_size),
                                          self._ctx.get_collection_alias(from_clause, True)[0])

        self.add_from_clause(expr, compiled)
        self._ctx.add_expr_compiled(expr, compiled)