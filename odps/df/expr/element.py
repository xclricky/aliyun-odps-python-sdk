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


from .expressions import TypedExpr, SequenceExpr, Scalar, \
    BooleanSequenceExpr, BooleanScalar, CollectionExpr, Expr
from . import utils
from . import errors
from .. import types


class AnyOp(TypedExpr):
    __slots__ = ()
    _add_args_slots = False

    @classmethod
    def _new_cls(cls, *args, **kwargs):
        if '_data_type' in kwargs:
            seq_cls = SequenceExpr._new_cls(cls, *args, **kwargs)
            if issubclass(cls, seq_cls):
                return cls
            bases = cls, seq_cls
        else:
            assert '_value_type' in kwargs

            scalar_cls = Scalar._new_cls(cls, *args, **kwargs)
            if issubclass(cls, scalar_cls):
                return cls
            bases = cls, scalar_cls

        return type(cls.__name__, bases, dict(cls.__dict__))


class ElementWise(AnyOp):
    __slots__ = ()
    _args = '_input',
    _add_args_slots = False

    @classmethod
    def _new_cls(cls, *args, **kwargs):
        base = AnyOp._new_cls(*args, **kwargs)

        if issubclass(cls, base):
            return cls

        dic = dict(cls.__dict__)
        dic['_args'] = cls._args
        if '_add_args_slots' in dic:
            del dic['_add_args_slots']
        return type(cls.__name__, (cls, base), dic)

    @property
    def node_name(self):
        return self.__class__.__name__

    @property
    def name(self):
        return self._name or self._input.name

    @property
    def input(self):
        return self._input

    def iter_args(self):
        for it in zip(['_input'] + [arg.lstrip('_') for arg in self._args[1:]],
                      self.args):
            yield it


class ElementOp(ElementWise):

    def accept(self, visitor):
        return visitor.visit_element_op(self)


class IsNull(ElementOp):
    __slots__ = ()


class NotNull(ElementOp):
    __slots__ = ()


class FillNa(ElementOp):
    _args = '_input', '_value'
    _add_args_slots = False

    def __init__(self, *args, **kwargs):
        self._value = None

        super(FillNa, self).__init__(*args, **kwargs)

        if self._value is not None and not isinstance(self._value, Expr):
            tp = types.validate_value_type(self._value)
            if not self.input.dtype.can_implicit_cast(tp):
                raise ValueError('fillna cannot cast value from %s to %s' % (
                    tp, self.input.dtype))
            self._value = Scalar(_value=self._value, _value_type=self.dtype)
        if not self.input.dtype.can_implicit_cast(self._value.dtype):
            raise ValueError('fillna cannot cast value from %s to %s' % (
                self._value.dtype, self.input.dtype))

    @property
    def value(self):
        if self._value is None:
            return
        if isinstance(self._value, Scalar):
            return self._value.value
        return self._value


class IsIn(ElementOp):
    _args = '_input', '_values',
    _add_args_slots = False

    def __init__(self, *args, **kwargs):
        super(IsIn, self).__init__(*args, **kwargs)

        self._values = _scalar(self._values, tp=self._input.dtype)
        if isinstance(self._values, list):
            self._values = tuple(self._values)
        if not isinstance(self._values, tuple):
            if not isinstance(self._values, SequenceExpr):
                raise ValueError('isin accept iterable object or sequence')
            self._values = (self._values, )

    @property
    def name(self):
        return self._name


class NotIn(ElementOp):
    _args = '_input', '_values',
    _add_args_slots = False

    def __init__(self, *args, **kwargs):
        super(NotIn, self).__init__(*args, **kwargs)

        self._values = _scalar(self._values, tp=self._input.dtype)
        if isinstance(self._values, list):
            self._values = tuple(self._values)
        if not isinstance(self._values, tuple):
            if not isinstance(self._values, SequenceExpr):
                raise ValueError('notin accept iterable object or sequence')
            self._values = (self._values, )

    @property
    def name(self):
        return self._name


class Between(ElementOp):
    _args = '_input', '_left', '_right', '_inclusive'
    _add_args_slots = False

    def __init__(self, *args, **kwargs):
        self._left = None
        self._right = None
        self._inclusive = None

        super(Between, self).__init__(*args, **kwargs)

        for attr in self._args[1:]:
            val = getattr(self, attr)
            if val is not None and not isinstance(val, Expr):
                setattr(self, attr, Scalar(_value=val))

    def _get_val(self, attr):
        val = getattr(self, attr)
        if val is None:
            return
        if isinstance(val, Scalar):
            return val.value
        return val

    @property
    def left(self):
        return self._get_val('_left')

    @property
    def right(self):
        return self._get_val('_right')

    @property
    def inclusive(self):
        return self._get_val('_inclusive')


class IfElse(ElementOp):
    _args = '_input', '_then', '_else'
    _add_args_slots = False

    @property
    def name(self):
        return self._name


class Switch(ElementOp):
    _args = '_input', '_case', '_conditions', '_thens', '_default'
    _add_args_slots = False

    def iter_args(self):
        def _names():
            yield 'case'
            for _ in self._conditions:
                yield 'when'
                yield 'then'
            yield 'default'

        def _args():
            yield self._case
            for condition, then in zip(self._conditions, self._thens):
                yield condition
                yield then
            yield self._default

        for it in zip(_names(), _args()):
            yield it

    @property
    def name(self):
        return self._name


class Cut(ElementOp):
    _args = '_input', '_bins', '_right', '_labels', '_include_lowest', \
            '_include_under', '_include_over'
    _add_args_slots = False

    def __init__(self, *args, **kwargs):
        super(Cut, self).__init__(*args, **kwargs)

        if len(self._bins) == 0:
            raise ValueError('Must be at least one bin edge')
        elif len(self._bins) == 1:
            if not self._include_under or not self._include_over:
                raise ValueError('If one bin edge provided, must have'
                                 ' include_under=True and include_over=True')

        for arg in self._args[1:]:
            obj = getattr(self, arg)
            setattr(self, arg, _scalar(obj))

        under = 1 if self._include_under.value else 0
        over = 1 if self._include_over.value else 0
        size = len(self._bins) - 1 + under + over

        if self._labels is not None and len(self._labels) != size:
            raise ValueError('Labels size must be exactly the size of bins')
        if self._labels is None:
            self._labels = _scalar(list(range(size)))

    @property
    def right(self):
        return self._right.value

    @property
    def include_lowest(self):
        return self._include_lowest.value

    @property
    def include_under(self):
        return self._include_under.value

    @property
    def include_over(self):
        return self._include_over.value

    @property
    def name(self):
        return self._name


def _isnull(expr):
    """
    Return a sequence or scalar according to the input indicating if the values are null.

    :param expr: sequence or scalar
    :return: sequence or scalar
    """

    if isinstance(expr, SequenceExpr):
        return IsNull(_input=expr, _data_type=types.boolean)
    elif isinstance(expr, Scalar):
        return IsNull(_input=expr, _value_type=types.boolean)


def _notnull(expr):
    """
    Return a sequence or scalar according to the input indicating if the values are not null.

    :param expr: sequence or scalar
    :return: sequence or scalar
    """

    if isinstance(expr, SequenceExpr):
        return NotNull(_input=expr, _data_type=types.boolean)
    elif isinstance(expr, Scalar):
        return NotNull(_input=expr, _value_type=types.boolean)


def _fillna(expr, value):
    """
    Fill null with value.

    :param expr: sequence or scalar
    :param value: value to fill into
    :return: sequence or scalar
    """

    if isinstance(expr, SequenceExpr):
        return FillNa(_input=expr, _value=value, _data_type=expr.dtype)
    elif isinstance(expr, Scalar):
        return FillNa(_input=expr, _value=value, _value_type=expr.dtype)


def _isin(expr, values):
    """
    Return a boolean sequence or scalar showing whether
    each element is exactly contained in the passed `values`.

    :param expr: sequence or scalar
    :param values: `list` object or sequence
    :return: boolean sequence or scalar
    """

    if isinstance(expr, SequenceExpr):
        return IsIn(_input=expr, _values=values, _data_type=types.boolean)
    elif isinstance(expr, Scalar):
        return IsIn(_input=expr, _values=values, _value_type=types.boolean)


def _notin(expr, values):
    """
    Return a boolean sequence or scalar showing whether
    each element is not contained in the passed `values`.

    :param expr: sequence or scalar
    :param values: `list` object or sequence
    :return: boolean sequence or scalar
    """

    if isinstance(expr, SequenceExpr):
        return NotIn(_input=expr, _values=values, _data_type=types.boolean)
    elif isinstance(expr, Scalar):
        return NotIn(_input=expr, _values=values, _value_type=types.boolean)


def _between(expr, left, right, inclusive=True):
    """
    Return a boolean sequence or scalar show whether
    each element is between `left` and `right`.

    :param expr: sequence or scalar
    :param left: left value
    :param right: right value
    :param inclusive: if true, will be left <= expr <= right, else will be left < expr < right
    :return: boolean sequence or scalar
    """

    if isinstance(expr, SequenceExpr):
        return Between(_input=expr, _left=left, _right=right,
                       _inclusive=inclusive, _data_type=types.boolean)
    elif isinstance(expr, Scalar):
        return Between(_input=expr, _left=left, _right=right,
                       _inclusive=inclusive, _value_type=types.boolean)


def _scalar(val, tp=None):
    if val is None:
        return
    if isinstance(val, Expr):
        return val
    if isinstance(val, (tuple, list)):
        return type(val)(_scalar(it, tp=tp) for it in val)
    else:
        return Scalar(_value=val, _value_type=tp)


def _ifelse(expr, true_expr, false_expr):
    """
    Given a boolean sequence or scalar, if true will return the left, else return the right one.

    :param expr: sequence or scalar
    :param true_expr:
    :param false_expr:
    :return: sequence or scalar

    :Example:

    >>> (df.id == 3).ifelse(df.id, df.fid.astype('int'))
    >>> df.isMale.ifelse(df.male_count, df.female_count)
    """

    tps = (SequenceExpr, Scalar)
    if not isinstance(true_expr, tps):
        true_expr = Scalar(_value=true_expr)
    if not isinstance(false_expr, tps):
        false_expr = Scalar(_value=false_expr)

    output_type = utils.highest_precedence_data_type(
            *[true_expr.dtype, false_expr.dtype])
    is_sequence = isinstance(expr, SequenceExpr) or \
                  isinstance(true_expr, SequenceExpr) or \
                  isinstance(false_expr, SequenceExpr)

    if is_sequence:
        return IfElse(_input=expr, _then=true_expr, _else=false_expr,
                      _data_type=output_type)
    else:
        return IfElse(_input=expr, _then=true_expr, _else=false_expr,
                      _value_type=output_type)


def _switch(expr, *args, **kw):
    """
    Similar to the case-when in SQL. Refer to the example below

    :param expr:
    :param args:
    :param kw:
    :return: sequence or scalar

    :Example:

    >>> # if df.id == 3 then df.name
    >>> # elif df.id == df.fid.abs() then df.name + 'test'
    >>> # default: 'test'
    >>> df.id.switch(3, df.name, df.fid.abs(), df.name + 'test', default='test')
    """
    default = _scalar(kw.get('default'))

    if len(args) <= 0:
        raise errors.ExpressionError('Switch must accept more than one condition')

    if all(isinstance(arg, tuple) and len(arg) == 2 for arg in args):
        conditions, thens = zip(*args)
    else:
        conditions = [arg for i, arg in enumerate(args) if i % 2 == 0]
        thens = [arg for i, arg in enumerate(args) if i % 2 == 1]

    if len(conditions) == len(thens):
        conditions, thens = _scalar(conditions), _scalar(thens)
    else:
        raise errors.ExpressionError('Switch should be called by case and then pairs')

    if isinstance(expr, (Scalar, SequenceExpr)):
        case = expr
    else:
        case = None
        if not all(hasattr(it, 'dtype') and it.dtype == types.boolean for it in conditions):
            raise errors.ExpressionError('Switch must be called by all boolean conditions')

    res = thens if default is None else thens + [default, ]
    output_type = utils.highest_precedence_data_type(*(it.dtype for it in res))

    is_seq = isinstance(expr, SequenceExpr) or \
        any(isinstance(it, SequenceExpr) for it in conditions) or \
        any(isinstance(it, SequenceExpr) for it in res)
    if case is not None:
        is_seq = is_seq or isinstance(case, SequenceExpr)

    kwargs = dict()
    if is_seq:
        kwargs['_data_type'] = output_type
    else:
        kwargs['_value_type'] = output_type
    return Switch(_input=expr, _case=case, _conditions=conditions,
                  _thens=thens, _default=default, **kwargs)


def switch(*args, **kwargs):
    return _switch(None, *args, **kwargs)


def _cut(expr, bins, right=True, labels=None, include_lowest=False,
         include_under=False, include_over=False):
    """
    Return indices of half-open bins to which each value of `expr` belongs.

    :param expr: sequence or scalar
    :param bins: list of scalars
    :param right: indicates whether the bins include the rightmost edge or not. If right == True(the default),
                  then the bins [1, 2, 3, 4] indicate (1, 2], (2, 3], (3, 4]
    :param labels: Usesd as labes for the resulting bins. Must be of the same length as the resulting bins.
    :param include_lowest: Whether the first interval should be left-inclusive or not.
    :param include_under: include the bin below the leftmost edge or not
    :param include_over: include the bin above the rightmost edge or not
    :return: sequence or scalar
    """

    is_seq = isinstance(expr, SequenceExpr)
    dtype = utils.highest_precedence_data_type(
        *(types.validate_value_type(it) for it in labels)) \
        if labels is not None else types.int64
    kw = {}
    if is_seq:
        kw['_data_type'] = dtype
    else:
        kw['_value_type'] = dtype

    return Cut(_input=expr, _bins=bins, _right=right, _labels=labels,
               _include_lowest=include_lowest, _include_under=include_under,
               _include_over=include_over, **kw)


_element_methods = dict(
    isnull=_isnull,
    notnull=_notnull,
    fillna=_fillna,
    between=_between,
    switch=_switch,
    cut=_cut,
    isin=_isin,
    notin=_notin,
)

utils.add_method(SequenceExpr, _element_methods)
utils.add_method(Scalar, _element_methods)

BooleanSequenceExpr.ifelse = _ifelse
BooleanScalar.ifelse = _ifelse

CollectionExpr.switch = _switch

