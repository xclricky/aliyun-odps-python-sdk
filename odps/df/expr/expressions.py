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

import inspect
import operator

import six
from six.moves import reduce

from .core import Node, NodeMetaclass
from .errors import ExpressionError
from .utils import get_attrs, is_called_by_inspector
from .. import types
from ...config import options
from ...errors import DependencyNotInstalledError


def run_at_once(func):
    func.run_at_once = True
    return func


def repr_obj(obj):
    if hasattr(obj, '_repr'):
        try:
            return obj._repr()
        except:
            return object.__repr__(obj)
    elif isinstance(obj, (tuple, list)):
        return ','.join(repr_obj(it) for it in obj)

    return obj


class Expr(Node):
    __slots__ = '__execution', '__ban_optimize', '_engine'

    def __init__(self, *args, **kwargs):
        self.__ban_optimize = False
        self._engine = None
        self.__execution = None
        super(Expr, self).__init__(*args, **kwargs)

    def __repr__(self):
        if not options.interactive or is_called_by_inspector():
            return self._repr()
        else:
            return self.__execution.__repr__()

    def _repr_html_(self):
        if not options.interactive:
            return '<code>' + repr(self) + '</code>'
        else:
            if hasattr(self.__execution, '_repr_html_'):
                return self.__execution._repr_html_()
            return repr(self.__execution)

    @run_at_once
    def execute(self, use_cache=None):
        """
        :param use_cache: use the executed result if has been executed
        :return: execution result
        :rtype: :class:`odps.df.backends.frame.ResultFrame`
        """

        if use_cache is None:
            use_cache = options.df.use_cache
        if use_cache and self.__execution:
            return self.__execution

        from ..engines import get_default_engine

        engine = get_default_engine(self)
        self.__execution = engine.execute(self)
        return self.__execution

    def compile(self):
        """
        Compile this expression into an ODPS SQL

        :return: compiled ODPS SQL
        :rtype: str
        """

        from ..engines import get_default_engine

        engine = get_default_engine(self)
        return engine.compile(self)

    @run_at_once
    def persist(self, name, partitions=None):
        """
        Persist the execution into a new table. If `partitions` not specfied,
        will create a new table without partitions, and insert the SQL result into it.
        If `partitions` are specified, they will be the partition fields of the new table.

        :param name: table name
        :param partitions: list of string, the partition fields
        :type partitions: list
        :return: :class:`odps.df.DataFrame`

        :Example:

        >>> df = df['name', 'id', 'ds']
        >>> df.persist('odps_new_table')
        >>> df.persist('odps_new_table', partitions=['ds'])
        """

        from ..engines import get_default_engine

        engine = get_default_engine(self)
        return engine.persist(self, name, partitions=partitions)

    def verify(self):
        """
        Verify if this expression can be compiled into ODPS SQL.

        :return: True if compilation succeed else False
        :rtype: bool
        """

        try:
            self.compile()

            return True
        except:
            return False

    def _repr(self):
        from .formatter import ExprFormatter

        formatter = ExprFormatter(self)
        return formatter()

    def ast(self):
        """
        Return the AST string.

        :return: AST tree
        :rtype: str
        """

        return self._repr()

    def _get_attr(self, attr):
        return object.__getattribute__(self, attr)

    def _get_arg(self, arg_name):
        args = self._get_attr('_args')
        cached_args = self._get_attr('_cached_args')
        if cached_args:
            return cached_args[args.index(arg_name)]
        return self._get_attr(arg_name)

    def __getattribute__(self, attr):
        try:
            if attr != '_get_attr' and attr in self._get_attr('_args'):
                return self._get_arg(attr)
            return object.__getattribute__(self, attr)
        except AttributeError as e:
            if not attr.startswith('_'):
                new_attr = '_%s' % attr
                if new_attr in self._get_attr('_args'):
                    return self._get_arg(new_attr)
            raise e

    def _defunc(self, field):
        return field(self) if inspect.isfunction(field) else field

    @property
    def optimize_banned(self):
        return self.__ban_optimize

    @optimize_banned.setter
    def optimize_banned(self, val):
        self.__ban_optimize = val

    def __hash__(self):
        # due to that the __eq__ cannot be used as compare
        return object.__hash__(self)

    def __eq__(self, other):
        try:
            return self._eq(other)
        except AttributeError:
            return super(Expr, self).__eq__(other)

    def __ne__(self, other):
        try:
            return self._ne(other)
        except AttributeError:
            return not super(Expr, self).__eq__(other)

    def __lt__(self, other):
        return self._lt(other)

    def __le__(self, other):
        return self._le(other)

    def __gt__(self, other):
        return self._gt(other)

    def __ge__(self, other):
        return self._ge(other)

    def __add__(self, other):
        return self._add(other)

    def __radd__(self, other):
        return self._radd(other)

    def __mul__(self, other):
        return self._mul(other)

    def __rmul__(self, other):
        return self._rmul(other)

    def __div__(self, other):
        return self._div(other)

    def __rdiv__(self, other):
        return self._rdiv(other)

    __truediv__ = __div__
    __rtruediv__ = __rdiv__

    def __floordiv__(self, other):
        return self._floordiv(other)

    def __rfloordiv__(self, other):
        return self._rfloordiv(other)

    def __sub__(self, other):
        return self._sub(other)

    def __rsub__(self, other):
        return self._rsub(other)

    def __pow__(self, power):
        return self._pow(power)

    def __rpow__(self, power):
        return self._rpow(power)

    def __or__(self, other):
        return self._or(other)

    def __ror__(self, other):
        return self._ror(other)

    def __and__(self, other):
        return self._and(other)

    def __rand__(self, other):
        return self._rand(other)

    def __neg__(self):
        return self._neg()

    def __invert__(self):
        return self._invert()

    def __abs__(self):
        return self._abs()


class CollectionExpr(Expr):
    """
    Collection represents for the two-dimensions data.

    :Example:

    >>> # projection
    >>> df = DataFrame(o.get_table('my_table')) # DataFrame is actually a CollectionExpr
    >>> df['name', 'id']  # projection some columns
    >>> df[[df.name, df.id]]  # projection
    >>> df[df]  # means nothing, but get all the columns
    >>> df[df, df.name.lower().rename('name2')]  # projection a new columns `name2` besides all the original columns
    >>> df.select(df, name2=df.name.lower())  # projection by `select`
    >>> df.exclude('name')  # projection all columns but `name`
    >>> df[df.exclude('name'), df.name.lower()]  # `name` will not conflict any more
    >>>
    >>> # filter
    >>> df[(df.id < 3) & (df.name != 'test')]
    >>> df.filter(df.id < 3, df.name != 'test')
    >>>
    >>> # slice
    >>> df[: 10]
    >>> df.limit(10)
    >>>
    >>> # Sequence
    >>> df.name # an instance of :class:`odps.df.expr.expressions.SequenceExpr`
    >>>
    >>> # schema or dtypes
    >>> df.dtypes
    odps.Schema {
      name    string
      id      int64
    }
    >>> df.schema
    odps.Schema {
      name    string
      id      int64
    }
    """

    __slots__ = '_schema', '_source_data'

    def __init__(self, *args, **kwargs):
        super(CollectionExpr, self).__init__(*args, **kwargs)
        if hasattr(self, '_schema') and any(it is None for it in self._schema.names):
            raise TypeError('Schema cannot has field which name is None')
        self._source_data = getattr(self, '_source_data', None)

    def __getitem__(self, item):
        if inspect.isfunction(item):
            item = self._defunc(item)
        if isinstance(item, (list, tuple)):
            item = [self._defunc(it) for it in item]
        if isinstance(item, CollectionExpr):
            item = [item, ]

        if isinstance(item, six.string_types):
            if item not in self._schema:
                raise ValueError('Field(%s) does not exist' % item)
            return Column(self, _name=item, _data_type=self._schema[item].type)
        elif isinstance(item, BooleanSequenceExpr): # need some constraint here to ensure `filter` correctness?
            return self._filter(item)
        elif isinstance(item, list) and all(isinstance(it, Scalar) for it in item):
            return self._summary(item)
        elif isinstance(item, list) and \
                all(self._validate_project_field(it) for it in item):
            return self._project(item)
        elif isinstance(item, slice):
            if item.start is None and item.stop is None and item.step is None:
                return self
            return self._slice(item)
        raise ExpressionError('Not supported projection: collection[%s]' % repr_obj(item))

    def _filter(self, predicate):
        return FilterCollectionExpr(self, predicate, _schema=self._schema)

    def filter(self, *predicates):
        """
        Filter the data by predicates

        :param predicates: the conditions to filter
        :return: new collection
        :rtype: :class:`odps.df.expr.expressions.CollectionExpr`
        """
        predicates = [self._defunc(it) for it in predicates]

        predicate = reduce(operator.and_, predicates)
        return self._filter(predicate)

    def _validate_field(self, field):
        if not isinstance(field, SequenceExpr):
            return True

        if not self._has_field(field):
            return False
        else:
            return True

    def _validate_project_field(self, field):
        if isinstance(field, six.string_types) and field in self._schema:
            return True
        elif isinstance(field, CollectionExpr):
            if field is self:
                return True
            elif isinstance(field, ProjectCollectionExpr) and \
                    field.input is self:
                return True
        elif not self._validate_field(field):
            return False
        return True

    def _has_field(self, field):
        if not field.is_ancestor(self):
            return False

        for path in field.all_path(self):
            if not all(not isinstance(n, CollectionExpr) for n in path[1: -1]):
                return False
        return True

    def _project(self, fields):
        names, typos, selects = [], [], []

        for field in fields:
            if isinstance(field, six.string_types):
                names.append(field)
                typos.append(self._schema.get_type(field))
                selects.append(field)
            elif isinstance(field, CollectionExpr):
                from .groupby import MutateCollectionExpr

                names.extend(field.schema.names)
                typos.extend(field.schema.types)
                if isinstance(field, (ProjectCollectionExpr,
                                      MutateCollectionExpr)):
                    selects.extend(field.fields)
                elif field is self:
                    selects.extend(field.schema.names)
                else:
                    raise ExpressionError('Cannot support projection on %s' % repr_obj(field))
            else:
                names.append(field.name)
                typos.append(field.dtype)
                selects.append(field)

        if any(n is None for n in names):
            raise ExpressionError('Cannot projection on non-name field')

        return ProjectCollectionExpr(self, _fields=selects,
                                     _schema=types.Schema.from_lists(names, typos))

    def select(self, *fields, **kw):
        """
        Projection columns. Remember to avoid column names' conflict.

        :param fields: columns to project
        :param kw: columns and their names to project
        :return: new collection
        :rtype: :class:`odps.df.expr.expression.CollectionExpr`
        """
        if len(fields) == 1 and isinstance(fields[0], list):
            fields = fields[0]
        else:
            fields = list(fields)
        fields = [self._defunc(it) for it in fields]
        if kw:
            fields.extend([self._defunc(f).rename(new_name)
                           for new_name, f in six.iteritems(kw)])

        return self._project(fields)

    def exclude(self, *fields):
        """
        Projection columns which not included in the fields

        :param fields: field names
        :return: new collection
        :rtype: :class:`odps.df.expr.expression.CollectionExpr`
        """

        if len(fields) == 1 and isinstance(fields[0], list):
            exclude_fields = fields[0]
        else:
            exclude_fields = list(fields)

        exclude_fields = [self._defunc(it) for it in exclude_fields]
        exclude_fields = [field.name if not isinstance(field, six.string_types) else field
                          for field in exclude_fields]

        fields = [name for name in self._schema.names
                  if name not in exclude_fields]

        return self._project(fields)

    def _summary(self, fields):
        names = [field if isinstance(field, six.string_types) else field.name
                 for field in fields]
        typos = [self._schema.get_type(field) if isinstance(field, six.string_types)
                 else field.dtype for field in fields]
        if None in names:
            raise ExpressionError('Column does not have a name, '
                                  'please specify one by `rename`')
        return Summary(_input=self, _fields=fields,
                       _schema=types.Schema.from_lists(names, typos))

    def _slice(self, slices):
        return SliceCollectionExpr(self, _indexes=slices, _schema=self._schema)

    @property
    def schema(self):
        return self._schema

    @property
    def columns(self):
        """
        :return: columns
        :rtype: list which each element is an instance of :class:`odps.models.Column`
        """

        return self._schema.columns

    def data_source(self):
        if hasattr(self, '_source_data') and self._source_data is not None:
            yield self._source_data

        for s in super(CollectionExpr, self).data_source():
            yield s

    def __getattr__(self, attr):
        try:
            obj = object.__getattribute__(self, attr)

            return obj
        except AttributeError as e:
            if attr in object.__getattribute__(self, '_schema'):
                return self[attr]

            raise e

    def output_type(self):
        return 'collection'

    def limit(self, n):
        return self[:n]

    @run_at_once
    def head(self, n=None):
        """
        Return the first n rows. Execute at once.

        :param n:
        :return: result frame
        :rtype: :class:`odps.df.backends.frame.ResultFrame`
        """
        if n is None:
            n = options.display.max_rows

        df = self.limit(n)

        return df.execute()

    @run_at_once
    def tail(self, n=None):
        """
        Return the last n rows. Execute at once.

        :param n:
        :return: result frame
        :rtype: :class:`odps.df.backends.frame.ResultFrame`
        """
        if n is None:
            n = options.display.max_rows

        from ..engines import get_default_engine

        engine = get_default_engine(self)
        result = engine._handle_cases(self, tail=n)

        if result:
            return result

        # TODO: The tail will not be supported until the instance tunnel is ready
        raise NotImplementedError

    @run_at_once
    def to_pandas(self, use_cache=None):
        """
        Convert to pandas DataFrame. Execute at once.

        :param use_cache: return executed result if have been executed
        :return: pandas DataFrame
        """

        try:
            import pandas as pd
        except ImportError:
            raise DependencyNotInstalledError(
                    'to_pandas requires for `pandas` library')

        return self.execute(use_cache=use_cache).values

    @property
    def dtypes(self):
        return self.schema

    def view(self):
        """
        Clone a same collection. useful for self-join.

        :return:
        """

        kv = dict((attr, getattr(self, attr)) for attr in get_attrs(self))
        return type(self)(**kv)

    def accept(self, visitor):
        if self._source_data is not None:
            visitor.visit_source_collection(self)
        else:
            raise NotImplementedError


class TypedExpr(Expr):
    __slots__ = '_name', '_source_name'

    @classmethod
    def _get_type(cls, *args, **kwargs):
        raise NotImplementedError

    @classmethod
    def _typed_classes(cls, *args, **kwargs):
        raise NotImplementedError

    @classmethod
    def _base_class(cls, *args, **kwargs):
        raise NotImplementedError

    @classmethod
    def _new_cls(cls, *args, **kwargs):
        data_type = cls._get_type(*args, **kwargs)
        if data_type:
            base_class = cls._base_class(*args, **kwargs)
            typed_classes = cls._typed_classes(*args, **kwargs)

            data_type = types.validate_data_type(data_type)
            name = data_type.__class__.__name__ + base_class.__name__
            typed_cls = globals().get(name)
            assert typed_cls is not None

            if issubclass(cls, typed_cls):
                return cls
            elif cls == base_class:
                return typed_cls
            elif cls in typed_classes:
                return typed_cls

            mros = inspect.getmro(cls)
            has_data_type = len([sub for sub in mros if sub in typed_classes]) > 0
            if has_data_type:
                mros = mros[1:]
            subs = [sub for sub in mros if sub not in typed_classes]
            subs.insert(1, typed_cls)

            bases = list()
            for sub in subs[::-1]:
                for i in range(len(bases)):
                    if bases[i] is None:
                        continue
                    if issubclass(sub, bases[i]):
                        bases[i] = None
                bases.append(sub)
            bases = tuple(base for base in bases if base is not None)

            clz = type(cls.__name__, bases, dict(cls.__dict__))
            return clz
        else:
            return cls

    def __new__(cls, *args, **kwargs):
        clz = cls._new_cls(*args, **kwargs)
        return object.__new__(clz)

    @classmethod
    def _new(cls, *args, **kwargs):
        return cls._new_cls(*args, **kwargs)(*args, **kwargs)

    def is_renamed(self):
        return self._name is not None and self._source_name is not None and \
               self._name != self._source_name

    def rename(self, new_name):
        if new_name == self._name:
            return self

        attr_dict = dict((attr, getattr(self, attr, None)) for attr in get_attrs(self))
        attr_dict['_source_name'] = self._source_name
        attr_dict['_name'] = new_name

        new_sequence = type(self)(**attr_dict)

        new_sequence._source_name = self._source_name
        new_sequence._name = new_name

        return new_sequence

    @property
    def name(self):
        return self._name

    @property
    def source_name(self):
        return self._source_name

    def astype(self, data_type):
        raise NotImplementedError

    def cast(self, t):
        return self.astype(t)


class SequenceExpr(TypedExpr):
    """
    Sequence represents for 1-dimension data.
    """

    __slots__ = '_data_type', '_source_data_type'

    @classmethod
    def _get_type(cls, *args, **kwargs):
        return types.validate_data_type(kwargs.get('_data_type'))

    @classmethod
    def _typed_classes(cls, *args, **kwargs):
        return _typed_sequence_exprs

    @classmethod
    def _base_class(cls, *args, **kwargs):
        return SequenceExpr

    def __init__(self, *args, **kwargs):
        self._name = None
        super(SequenceExpr, self).__init__(*args, **kwargs)

        if '_data_type' in kwargs:
            self._data_type = types.validate_data_type(kwargs.get('_data_type'))

        if '_source_name' not in kwargs:
            self._source_name = self._name

        if '_source_data_type' in kwargs:
            self._source_data_type = types.validate_data_type(kwargs.get('_source_data_type'))
        else:
            self._source_data_type = self._data_type

    @run_at_once
    def head(self, n=None):
        """
        Return first n rows. Execute at once.

        :param n:
        :return: result frame
        :rtype: :class:`odps.df.expr.expressions.CollectionExpr`
        """

        from ..engines import get_default_engine

        engine = get_default_engine(self)

        collection = engine._ctx.get_replaced_expr(self)
        if collection is None:
            collection = engine._convert_table(self)
        return collection.head(n=n)

    @run_at_once
    def tail(self, n=None):
        """
        Return the last n rows. Execute at once.

        :param n:
        :return:
        """

        from ..engines import get_default_engine

        engine = get_default_engine(self)

        collection = engine._ctx.get_replaced_expr(self)
        if collection is None:
            collection = engine._convert_table(self)
        return collection.tail(n=n)

    @run_at_once
    def to_pandas(self, use_cache=None):
        """
        Convert to pandas Series. Execute at once.

        :param use_cache: return executed result if have been executed
        :return: pandas Series
        """

        try:
            import pandas as pd
        except ImportError:
            raise DependencyNotInstalledError(
                    'to_pandas requires for `pandas` library')

        df = self.execute(use_cache=use_cache).values
        return df[self.name]

    @property
    def data_type(self):
        return self._data_type

    @property
    def source_data_type(self):
        return self._source_data_type

    @property
    def dtype(self):
        """
        Return the data type. Available types:
        int8, int16, int32, int64, float32, float64, boolean, string, decimal, datetime

        :return: the data type
        """
        return self._data_type

    def astype(self, data_type):
        """
        Cast to a new data type.

        :param data_type: the new data type
        :return: casted sequence

        :Example:

        >>> df.id.astype('float')
        """

        data_type = types.validate_data_type(data_type)

        if data_type == self._data_type:
            return self

        attr_dict = dict()
        attr_dict['_data_type'] = data_type
        attr_dict['_source_data_type'] = self._source_data_type
        attr_dict['_input'] = self

        new_sequence = AsTypedSequenceExpr(**attr_dict)

        return new_sequence

    def output_type(self):
        return 'sequence(%s)' % repr(self._data_type)

    def map(self, func, rtype=None):
        """
        Call func on each element of this sequence.

        :param func: lambda or function
        :param rtype: if not provided, will be the dtype of this sequence
        :return: a new sequence

        :Example:

        >>> df.id.map(lambda x: x + 1)
        """

        rtype = rtype or self._data_type
        output_type = types.validate_data_type(rtype)

        if not inspect.isfunction(func):
            raise ValueError('`func` must be a function')

        return MappedSequenceExpr(_data_type=output_type, _func=func, _input=self)

    def accept(self, visitor):
        visitor.visit_sequence(self)


class BooleanSequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(BooleanSequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.boolean


class Int8SequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(Int8SequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.int8


class Int16SequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(Int16SequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.int16


class Int32SequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(Int32SequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.int32


class Int64SequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(Int64SequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.int64


class Float32SequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(Float32SequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.float32


class Float64SequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(Float64SequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.float64


class DecimalSequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(DecimalSequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.decimal


class StringSequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(StringSequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.string


class DatetimeSequenceExpr(SequenceExpr):
    def __init__(self, *args, **kwargs):
        super(DatetimeSequenceExpr, self).__init__(*args, **kwargs)
        self._data_type = types.datetime


_typed_sequence_exprs = [globals()[t.__class__.__name__ + SequenceExpr.__name__]
                         for t in types._data_types.values()]


class AsTypedSequenceExpr(SequenceExpr):
    _args = '_input',
    node_name = "TypedSequence"

    @property
    def input(self):
        if self._cached_args:
            return self._cached_args[0]
        return self._input

    def accept(self, visitor):
        return visitor.visit_cast(self)

    @property
    def name(self):
        return self._name or self._input.name

    @property
    def source_name(self):
        return self._source_name or self._input.source_name

    @property
    def dtype(self):
        return self._data_type or self._input.data_type

    @property
    def source_type(self):
        return self._source_data_type or self._input._source_data_type


class Column(SequenceExpr):
    _args = '_input',

    @property
    def input(self):
        if self._cached_args:
            return self._cached_args[0]
        return self._input

    def accept(self, visitor):
        return visitor.visit_column(self)


class MappedSequenceExpr(SequenceExpr):
    __slots__ = '_func',
    _args = '_input',
    node_name = 'Map'

    @property
    def input(self):
        return self._input

    @property
    def name(self):
        return self._name or self._input.name

    @property
    def source_name(self):
        return self._source_name or self._input.source_name

    @property
    def input_type(self):
        return self._input.data_type

    def accept(self, visitor):
        return visitor.visit_map(self)


class Scalar(TypedExpr):
    """
    Represent for the scalar type.
    """

    __slots__ = '_value', '_value_type', '_source_value_type'

    @classmethod
    def _get_type(cls, *args, **kwargs):
        value = args[0] if len(args) > 0 else None
        value_type = args[1] if len(args) > 1 else None

        val = kwargs.get('_value')
        if val is None:
            val = value

        value_type = kwargs.get('_value_type', None) or value_type

        if val is None and value_type is None:
            raise ValueError('Either value or value_type should be provided')

        if not isinstance(val, NodeMetaclass):
            return types.validate_value_type(val, value_type)
        else:
            return value_type

    @classmethod
    def _typed_classes(cls, *args, **kwargs):
        return _typed_scalar_exprs

    @classmethod
    def _base_class(cls, *args, **kwargs):
        return Scalar

    def __init__(self, *args, **kwargs):
        self._name = None

        value = args[0] if len(args) > 0 else None
        value_type = args[1] if len(args) > 1 else None

        super(Scalar, self).__init__(**kwargs)

        val = getattr(self, '_value', None)
        if val is None:
            val = value

        self._value = val
        self._value_type = getattr(self, '_value_type', None) or value_type
        self._value_type = types.validate_value_type(self._value, self._value_type)

        if '_source_name' not in kwargs:
            self._source_name = self._name

        if '_source_value_type' in kwargs:
            self._source_value_type = types.validate_data_type(kwargs.get('_source_value_type'))
        else:
            self._source_value_type = self._value_type

    def equals(self, other):
        return super(Scalar, self).equals(other)

    @property
    def value(self):
        return self._value

    @property
    def value_type(self):
        return self._value_type

    @property
    def dtype(self):
        return self._value_type

    def output_type(self):
        return 'Scalar[%s]' % repr(self._value_type)

    def astype(self, value_type):
        value_type = types.validate_data_type(value_type)

        if value_type == self._value_type:
            return self

        attr_dict = dict()

        attr_dict['_input'] = self
        attr_dict['_value_type'] = value_type
        attr_dict['_source_value_type'] = self._source_value_type

        new_scalar = AsTypedScalar(**attr_dict)

        return new_scalar

    def to_sequence(self):
        if self._value is None:
            attr_values = dict((attr, getattr(self, attr)) for attr in get_attrs(self))

            kw = {
                '_data_type': attr_values['_value_type']
            }
            if '_source_value_type' in kw:
                kw['_source_data_type'] = kw.pop('_source_value_type')

            cls = next(c for c in inspect.getmro(type(self))[1:]
                       if c.__name__ == type(self).__name__ and not issubclass(c, Scalar))
            seq = cls._new(**kw)

            for attr, value in six.iteritems(attr_values):
                try:
                    setattr(seq, attr, value)
                except AttributeError:
                    continue
            return seq

        raise ExpressionError('Cannot convert valued scalar to sequence')

    def accept(self, visitor):
        if self._value is not None:
            visitor.visit_scalar(self)
        else:
            raise NotImplementedError


class AsTypedScalar(Scalar):
    _args = '_input',
    node_name = "TypedScalar"

    def accept(self, visitor):
        return visitor.visit_cast(self)

    @property
    def name(self):
        return self._name or self._input.name

    @property
    def source_name(self):
        return self._source_name or self._input.source_name

    @property
    def value(self):
        return self._value

    @property
    def value_type(self):
        return self._value_type

    @property
    def dtype(self):
        return self._value_type

    @property
    def source_type(self):
        return self._source_value_type


class BooleanScalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(BooleanScalar, self).__init__(*args, **kwargs)
        self._value_type = types.boolean


class Int8Scalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(Int8Scalar, self).__init__(*args, **kwargs)
        self._value_type = types.int8


class Int16Scalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(Int16Scalar, self).__init__(*args, **kwargs)
        self._value_type = types.int16


class Int32Scalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(Int32Scalar, self).__init__(*args, **kwargs)
        self._value_type = types.int32


class Int64Scalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(Int64Scalar, self).__init__(*args, **kwargs)
        self._value_type = types.int64


class Float32Scalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(Float32Scalar, self).__init__(*args, **kwargs)
        self._value_type = types.float32


class Float64Scalar(Scalar):
    def __int__(self, *args, **kwargs):
        super(Float64Scalar, self).__init__(*args, **kwargs)
        self._value_type = types.float64


class DecimalScalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(DecimalScalar, self).__init__(*args, **kwargs)
        self._value_type = types.decimal


class StringScalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(StringScalar, self).__init__(*args, **kwargs)
        self._value_type = types.string


class DatetimeScalar(Scalar):
    def __init__(self, *args, **kwargs):
        super(DatetimeScalar, self).__init__(*args, **kwargs)
        self._value_type = types.datetime


_typed_scalar_exprs = [globals()[t.__class__.__name__ + Scalar.__name__]
                       for t in types._data_types.values()]


class FilterCollectionExpr(CollectionExpr):
    _args = '_input', '_predicate'
    node_name = 'Filter'

    def __init__(self, *args, **kwargs):
        super(FilterCollectionExpr, self).__init__(*args, **kwargs)

        if self._schema is None:
            self._schema = self._input.schema

    def iter_args(self):
        for it in zip(['collection', 'predicate'], self.args):
            yield it

    @property
    def input(self):
        return self._input

    def accept(self, visitor):
        visitor.visit_filter_collection(self)


class ProjectCollectionExpr(CollectionExpr):
    _args = '_input', '_fields'
    node_name = 'Projection'

    def __init__(self, *args, **kwargs):
        fields = kwargs.get('_fields')
        if fields is None and len(args) >= 2:
            fields = args[1]
        for field in fields:
            if isinstance(field, SequenceExpr) and field.name is None:
                raise ExpressionError('Column does not have a name, '
                                      'please specify one by `rename`: %s' % repr_obj(field._repr()))

        super(ProjectCollectionExpr, self).__init__(*args, **kwargs)

        get_field = lambda field: Column(
            self._input, _name=field, _data_type=self._schema[field].type)
        self._fields = [get_field(field) if isinstance(field, six.string_types) else field
                        for field in self._fields]

    def iter_args(self):
        for it in zip(['collection', 'selections'], self.args):
            yield it

    @property
    def input(self):
        return self._input

    def accept(self, visitor):
        visitor.visit_project_collection(self)


class SliceCollectionExpr(CollectionExpr):
    _args = '_input', '_indexes'
    node_name = 'Slice'

    def __init__(self, *args, **kwargs):
        super(SliceCollectionExpr, self).__init__(*args, **kwargs)

        if isinstance(self._indexes, slice):
            scalar = lambda v: Scalar(_value=v) if v is not None else None
            self._indexes = scalar(self._indexes.start), \
                            scalar(self._indexes.stop), scalar(self._indexes.step)

    @property
    def start(self):
        return self._indexes[0].value

    @property
    def stop(self):
        return self._indexes[1].value

    @property
    def step(self):
        return self._indexes[2].value

    @property
    def input(self):
        return self._input

    def iter_args(self):
        args = [self._input] + list(self._indexes)
        for it in zip(['collection', 'start', 'stop', 'step'], args):
            yield it

    def accept(self, visitor):
        visitor.visit_slice_collection(self)


class Summary(Expr):
    __slots__ = '_schema',
    _args = '_input', '_fields'

    def __init__(self, *args, **kwargs):
        super(Summary, self).__init__(*args, **kwargs)
        if hasattr(self, '_schema') and any(it is None for it in self._schema.names):
            raise TypeError('Schema cannot has field which name is None')

    @property
    def input(self):
        return self._input

    @property
    def fields(self):
        return self._fields

    def iter_args(self):
        for it in zip(['collection', 'fields'], self.args):
            yield it

    def accept(self, visitor):
        visitor.visit_project_collection(self)


from . import element
from . import arithmetic
from . import reduction
from . import groupby
from . import collections
from . import window
from . import math
from . import strings
from . import datetimes
from . import merge
from ..tools import plotting


# hack for count
def _count(expr, *args, **kwargs):
    if len(args) + len(kwargs) > 0:
        from .strings import _count
        return _count(expr, *args, **kwargs)
    else:
        from .reduction import count
        return count(expr)


StringSequenceExpr.count = _count
