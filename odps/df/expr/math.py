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

from .expressions import *
from .arithmetic import UnaryOp, number_sequences, number_scalars
from . import utils
from .. import types


class Math(UnaryOp):
    __slots__ = ()

    def accept(self, visitor):
        return visitor.visit_math(self)


class Abs(Math):
    __slots__ = ()


class Sqrt(Math):
    __slots__ = ()


class Sin(Math):
    __slots__ = ()


class Sinh(Math):
    __slots__ = ()


class Cos(Math):
    __slots__ = ()


class Cosh(Math):
    __slots__ = ()


class Tan(Math):
    __slots__ = ()


class Tanh(Math):
    __slots__ = ()


class Exp(Math):
    __slots__ = ()


class Expm1(Math):
    __slots__ = ()


class Log(Math):
    __slots__ = ()
    _args = '_input', '_base'
    _add_args_slots = False

    def __init__(self, *args, **kwargs):
        self._base = None
        super(Log, self).__init__(*args, **kwargs)


class Log10(Math):
    __slots__ = ()


class Log2(Math):
    __slots__ = ()


class Log1p(Math):
    __slots__ = ()


class Arccos(Math):
    __slots__ = ()


class Arccosh(Math):
    __slots__ = ()


class Arcsin(Math):
    __slots__ = ()


class Arcsinh(Math):
    __slots__ = ()


class Arctan(Math):
    __slots__ = ()


class Arctanh(Math):
    __slots__ = ()


class Radians(Math):
    __slots__ = ()


class Degrees(Math):
    __slots__ = ()


class Ceil(Math):
    __slots__ = ()


class Floor(Math):
    __slots__ = ()


class Trunc(Math):
    __slots__ = ()
    _args = '_input', '_decimals'
    _add_args_slots = False

    def __init__(self, *args, **kwargs):
        self._decimals = None
        super(Trunc, self).__init__(*args, **kwargs)


def _math(expr, math_cls, output_type):
    if isinstance(expr, SequenceExpr):
        return math_cls(_input=expr, _data_type=output_type)
    elif isinstance(expr, Scalar):
        return math_cls(_input=expr, _value_type=output_type)


def _abs(expr):
    return _math(expr, Abs, expr.dtype)


def _get_type(expr):
    if expr.dtype == types.decimal:
        return types.decimal
    else:
        return types.float64


def _sqrt(expr):
    return _math(expr, Sqrt, _get_type(expr))


def _sin(expr):
    return _math(expr, Sin, _get_type(expr))


def _sinh(expr):
    return _math(expr, Sinh, _get_type(expr))


def _cos(expr):
    return _math(expr, Cos, _get_type(expr))


def _cosh(expr):
    return _math(expr, Cosh, _get_type(expr))


def _tan(expr):
    return _math(expr, Tan, _get_type(expr))


def _tanh(expr):
    return _math(expr, Tanh, _get_type(expr))


def _exp(expr):
    return _math(expr, Exp, _get_type(expr))


def _expm1(expr):
    return _math(expr, Expm1, _get_type(expr))


def _log(expr, base=None):
    log = _math(expr, Log, _get_type(expr))
    if base is not None and not isinstance(base, Scalar):
        base = Scalar(_value=base)
    log._base = base

    return log


def _log2(expr):
    return _math(expr, Log2, _get_type(expr))


def _log10(expr):
    return _math(expr, Log10, _get_type(expr))


def _log1p(expr):
    return _math(expr, Log1p, _get_type(expr))


def _arccos(expr):
    return _math(expr, Arccos, _get_type(expr))


def _arccosh(expr):
    return _math(expr, Arccosh, _get_type(expr))


def _arcsin(expr):
    return _math(expr, Arcsin, _get_type(expr))


def _arcsinh(expr):
    return _math(expr, Arcsinh, _get_type(expr))


def _arctan(expr):
    return _math(expr, Arctan, _get_type(expr))


def _arctanh(expr):
    return _math(expr, Arctanh, _get_type(expr))


def _radians(expr):
    return _math(expr, Radians, _get_type(expr))


def _degrees(expr):
    return _math(expr, Degrees, _get_type(expr))


def _ceil(expr):
    return _math(expr, Ceil, types.int64)


def _floor(expr):
    return _math(expr, Floor, types.int64)


def _trunc(expr, decimals=None):
    truncated = _math(expr, Trunc, _get_type(expr))
    if decimals is not None and not isinstance(decimals, Scalar):
        decimals = Scalar(_value=decimals)
    truncated._decimals = decimals

    return truncated


_number_methods = dict(
    abs=_abs,
    sqrt=_sqrt,
    sin=_sin,
    sinh=_sinh,
    cos=_cos,
    cosh=_cosh,
    tan=_tan,
    tanh=_tanh,
    exp=_exp,
    expm1=_expm1,
    log=_log,
    log2=_log2,
    log10=_log10,
    log1p=_log1p,
    arccos=_arccos,
    arccosh=_arccosh,
    arcsin=_arcsin,
    arcsinh=_arcsinh,
    arctan=_arctan,
    arctanh=_arctanh,
    radians=_radians,
    degrees=_degrees,
    ceil=_ceil,
    floor=_floor,
    trunc=_trunc
)


for number_sequence in number_sequences + number_scalars:
    utils.add_method(number_sequence, _number_methods)