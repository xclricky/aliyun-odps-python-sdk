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

import itertools

import six
from six.moves.builtins import zip
from six import StringIO
try:
    import pandas as pd
    has_pandas = True
except ImportError:
    has_pandas = False

from ...compat import u
from ...config import options
from ...console import get_console_size, in_interactive_session, \
    in_ipython_frontend, in_qtconsole
from . import formatter as fmt


class ResultFrame(six.Iterator):
    def __init__(self, data, columns=None, schema=None, index=None, pandas=True):
        if columns is None and schema is None:
            raise ValueError('Either columns or schema should be provided')

        if columns is None and schema is not None:
            columns = schema.columns

        self._columns = columns
        self._index = index

        if has_pandas and pandas:
            self._values = pd.DataFrame([self._get_values(r) for r in data],
                                        columns=[col.name for col in self._columns],
                                        index=index)
            self._index = self._values.index
            self._pandas = True
        else:
            if self._index is None:
                self._index = []
                self._values = []
                for i, r in zip(itertools.count(0), data):
                    self._values.append(self._get_values(r))
                    self._index.append(i)
            else:
                self._values = list(self._get_values(r) for r in data)
            self._pandas = False

        self._cursor = -1

    def _get_values(self, r):
        if hasattr(r, 'values'):
            return r.values
        return r

    @property
    def columns(self):
        return self._columns

    @property
    def index(self):
        return self._index

    @property
    def values(self):
        return self._values

    def __getitem__(self, item):
        if isinstance(item, six.integer_types):
            if self._pandas:
                return self._values.iloc[item]
            else:
                return self._values[item]
        elif isinstance(item, slice):
            if self._pandas:
                return self._values.iloc[item]
            else:
                return ResultFrame(self._values[item], columns=self._columns,
                                   index=self._index[item], pandas=self._pandas)
        elif isinstance(item, tuple) and len(item) == 2:
            if self._pandas:
                return self._values.iloc[item]
            else:
                if isinstance(item[1], slice):
                    frame = self[item[0]]
                    values = [r[item[1]] for r in frame._values]
                    return ResultFrame(values, columns=self._columns[item[1]],
                                       index=frame._index, pandas=self._pandas)
                else:
                    values = [r[item[1]] for r in self[item[0]]._values]
                    return values

    def __next__(self):
        self._cursor += 1
        try:
            if self._pandas:
                return self._values.iloc[self._cursor]
            else:
                return self._values[self._cursor]
        except IndexError:
            raise StopIteration

    def __iter__(self):
        while True:
            try:
                yield next(self)
            except StopIteration:
                return

    def concat(self, frame, axis=0):
        if self._pandas:
            from pandas.tools.merge import concat

            return concat((self, frame), axis=axis)
        else:
            if axis == 0:
                if self._columns != frame._columns:
                    raise ValueError(
                        'Cannot concat two frame of different columns')

                return ResultFrame(self._values + frame._values, columns=self._columns,
                                   index=self._index + frame._index, pandas=self._pandas)
            else:
                if self._index != frame._index:
                    raise ValueError(
                        'Cannot concat two frames of different indexes')

                values = [val+other for val, other in zip(self._values, frame._values)]
                return ResultFrame(values, self._columns + frame._columns,
                                   index=self._index, pandas=self._pandas)

    @property
    def dtypes(self):
        return [it.type for it in self._columns]

    def __len__(self):
        return len(self._values)

    def _repr_fits_vertical_(self):
        """
        Check length against max_rows.
        """
        max_rows = options.display.max_rows
        return len(self) <= max_rows

    def _repr_fits_horizontal_(self, ignore_width=False):
        """
        Check if full repr fits in horizontal boundaries imposed by the display
        options width and max_columns. In case off non-interactive session, no
        boundaries apply.

        ignore_width is here so ipnb+HTML output can behave the way
        users expect. display.max_columns remains in effect.
        GH3541, GH3573
        """

        width, height = get_console_size()
        max_columns = options.display.max_columns
        nb_columns = len(self.columns)

        # exceed max columns
        if ((max_columns and nb_columns > max_columns) or
                ((not ignore_width) and width and nb_columns > (width // 2))):
            return False

        if (ignore_width  # used by repr_html under IPython notebook
                # scripts ignore terminal dims
                or not in_interactive_session()):
            return True

        if (options.display.width is not None or
                in_ipython_frontend()):
            # check at least the column row for excessive width
            max_rows = 1
        else:
            max_rows = options.display.max_rows

        # when auto-detecting, so width=None and not in ipython front end
        # check whether repr fits horizontal by actualy checking
        # the width of the rendered repr
        buf = StringIO()

        # only care about the stuff we'll actually print out
        # and to_string on entire frame may be expensive
        d = self

        if not (max_rows is None):  # unlimited rows
            # min of two, where one may be None
            d = d[:min(max_rows, len(d))]
        else:
            return True

        d.to_string(buf=buf)
        value = buf.getvalue()
        repr_width = max([len(l) for l in value.split('\n')])

        return repr_width < width

    def __repr__(self):
        """
        Return a string representation for a particular DataFrame

        Invoked by unicode(df) in py2 only. Yields a Unicode String in both
        py2/py3.
        """
        if self._pandas:
            return repr(self._values)

        buf = StringIO(u(""))

        max_rows = options.display.max_rows
        max_cols = options.display.max_columns
        show_dimensions = options.display.show_dimensions
        if options.display.expand_frame_repr:
            width, _ = get_console_size()
        else:
            width = None
        self.to_string(buf=buf, max_rows=max_rows, max_cols=max_cols,
                       line_width=width, show_dimensions=show_dimensions)

        return buf.getvalue()

    def _repr_html_(self):
        """
        Return a html representation for a particular DataFrame.
        Mainly for IPython notebook.
        """
        # qtconsole doesn't report its line width, and also
        # behaves badly when outputting an HTML table
        # that doesn't fit the window, so disable it.
        # XXX: In IPython 3.x and above, the Qt console will not attempt to
        # display HTML, so this check can be removed when support for IPython 2.x
        # is no longer needed.
        if self._pandas:
            return self._values._repr_html_()

        if in_qtconsole():
            # 'HTML output is disabled in QtConsole'
            return None

        if options.display.notebook_repr_html:
            max_rows = options.display.max_rows
            max_cols = options.display.max_columns
            show_dimensions = options.display.show_dimensions

            return self.to_html(max_rows=max_rows, max_cols=max_cols,
                                show_dimensions=show_dimensions,
                                notebook=True)
        else:
            return None

    def to_string(self, buf=None, columns=None, col_space=None,
                  header=True, index=True, na_rep='NaN', formatters=None,
                  float_format=None, sparsify=None, index_names=True,
                  justify=None, line_width=None, max_rows=None, max_cols=None,
                  show_dimensions=False):
        """
        Render a DataFrame to a console-friendly tabular output.
        """

        formatter = fmt.ResultFrameFormatter(self, buf=buf, columns=columns,
                                             col_space=col_space, na_rep=na_rep,
                                             formatters=formatters,
                                             float_format=float_format,
                                             sparsify=sparsify,
                                             justify=justify,
                                             index_names=index_names,
                                             header=header, index=index,
                                             line_width=line_width,
                                             max_rows=max_rows,
                                             max_cols=max_cols,
                                             show_dimensions=show_dimensions)
        formatter.to_string()

        if buf is None:
            result = formatter.buf.getvalue()
            return result

    def to_html(self, buf=None, columns=None, col_space=None,
                header=True, index=True, na_rep='NaN', formatters=None,
                float_format=None, sparsify=None, index_names=True,
                justify=None, bold_rows=True, classes=None, escape=True,
                max_rows=None, max_cols=None, show_dimensions=False,
                notebook=False):
        """
        Render a DataFrame as an HTML table.

        `to_html`-specific options:

        bold_rows : boolean, default True
            Make the row labels bold in the output
        classes : str or list or tuple, default None
            CSS class(es) to apply to the resulting html table
        escape : boolean, default True
            Convert the characters <, >, and & to HTML-safe sequences.=
        max_rows : int, optional
            Maximum number of rows to show before truncating. If None, show
            all.
        max_cols : int, optional
            Maximum number of columns to show before truncating. If None, show
            all.

        """

        formatter = fmt.ResultFrameFormatter(self, buf=buf, columns=columns,
                                             col_space=col_space, na_rep=na_rep,
                                             formatters=formatters,
                                             float_format=float_format,
                                             sparsify=sparsify,
                                             justify=justify,
                                             index_names=index_names,
                                             header=header, index=index,
                                             bold_rows=bold_rows,
                                             escape=escape,
                                             max_rows=max_rows,
                                             max_cols=max_cols,
                                             show_dimensions=show_dimensions)
        formatter.to_html(classes=classes, notebook=notebook)

        if buf is None:
            return formatter.buf.getvalue()