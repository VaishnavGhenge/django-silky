import logging
import os
import sys
import traceback

from django.core.exceptions import EmptyResultSet
from django.utils import timezone
from django.utils.encoding import force_str

from silk.collector import DataCollector
from silk.config import SilkyConfig

Logger = logging.getLogger('silk.sql')

_TEMPLATE_BASE = os.path.join('django', 'template', 'base.py')
_TAG = {'VAR': '{{ %s }}', 'BLOCK': '{%% %s %%}'}


def _template_frame(frame):
    """A traceback entry for the template line a Node.render_annotated frame is rendering, or ''.

    Django's template engine is library code, so without this a query run by
    {{ obj.customer.name }} is blamed on the view's render() call. Every parsed
    node carries its origin (the template file) and token (with its line).
    """
    code = frame.f_code
    if code.co_name != 'render_annotated' or not code.co_filename.endswith(_TEMPLATE_BASE):
        return ''
    node = frame.f_locals.get('self')
    origin, token = getattr(node, 'origin', None), getattr(node, 'token', None)
    name, lineno = getattr(origin, 'name', ''), getattr(token, 'lineno', None)
    if not name or name.startswith('<') or not lineno:
        return ''
    source = _TAG.get(token.token_type.name, '%s') % token.contents
    return '  File "%s", line %d, in template\n    %s\n' % (name, lineno, ' '.join(source.split()))


def _stack():
    """The caller's stack formatted like traceback.format_stack(), innermost call first, with template lines."""
    out = []
    for frame, lineno in traceback.walk_stack(sys._getframe(1)):
        out.append(_template_frame(frame))
        out.extend(traceback.StackSummary.extract([(frame, lineno)]).format())
    return ''.join(out)


def _should_wrap(sql_query):
    if not DataCollector().request:
        return False

    for ignore_str in SilkyConfig().SILKY_IGNORE_QUERIES:
        if ignore_str in sql_query:
            return False
    return True


def _unpack_explanation(result):
    for row in result:
        if not isinstance(row, str):
            yield ' '.join(str(c) for c in row)
        else:
            yield row


def _explain_query(connection, q, params):
    if connection.features.supports_explaining_query_execution:
        if SilkyConfig().SILKY_ANALYZE_QUERIES:
            # Work around some DB engines not supporting analyze option
            try:
                prefix = connection.ops.explain_query_prefix(
                    analyze=True, **(SilkyConfig().SILKY_EXPLAIN_FLAGS or {})
                )
            except ValueError as error:
                error_str = str(error)
                if error_str.startswith("Unknown options:"):
                    Logger.warning(
                        "Database does not support analyzing queries with provided params. %s."
                        "SILKY_ANALYZE_QUERIES option will be ignored",
                        error_str
                    )
                    prefix = connection.ops.explain_query_prefix()
                else:
                    raise error
        else:
            prefix = connection.ops.explain_query_prefix()

        # currently we cannot use explain() method
        # for queries other than `select`
        if q.upper().startswith(prefix.upper()):
            # to avoid "EXPLAIN EXPLAIN", do not add prefix
            prefixed_query = q
        else:
            prefixed_query = f"{prefix} {q}"
        with connection.cursor() as cur:
            cur.execute(prefixed_query, params)
            result = _unpack_explanation(cur.fetchall())
            return '\n'.join(result)
    return None


def execute_sql(self, *args, **kwargs):
    """wrapper around real execute_sql in order to extract information"""

    try:
        q, params = self.as_sql()
        if not q:
            raise EmptyResultSet
    except EmptyResultSet:
        try:
            result_type = args[0]
        except IndexError:
            result_type = kwargs.get('result_type', 'multi')
        if result_type == 'multi':
            return iter([])
        else:
            return
    try:
        sql_query = q % tuple(force_str(param) for param in params)
    except UnicodeDecodeError:
        # Sometimes `force_str` can still raise a UnicodeDecodeError
        # Reference: https://github.com/jazzband/django-silk/issues?q=encoding
        # This could log a warning but given this is run in the hot path, logging could be too expensive.
        return self._execute_sql(*args, **kwargs)
    if _should_wrap(sql_query):
        tb = _stack()
        query_dict = {
            'query': sql_query,
            'start_time': timezone.now(),
            'traceback': tb
        }
        try:
            return self._execute_sql(*args, **kwargs)
        finally:
            query_dict['end_time'] = timezone.now()
            request = DataCollector().request
            if request:
                query_dict['request'] = request
            if getattr(self.query.model, '__module__', '') != 'silk.models':
                query_dict['analysis'] = _explain_query(self.connection, q, params)
                DataCollector().register_query(query_dict)
            else:
                DataCollector().register_silk_query(query_dict)
    return self._execute_sql(*args, **kwargs)
