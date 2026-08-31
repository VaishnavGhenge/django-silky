"""Per-row SQL aggregates that don't group by the whole row.

``Request.objects.annotate(num_queries=Count('queries'))`` selects every column
of ``silk_request`` and, on every backend except PostgreSQL, groups by every one
of them. Five of those columns are ``TextField``, which Oracle stores as NCLOB,
and Oracle refuses to GROUP BY a LOB: ``ORA-00932: inconsistent datatypes:
expected - got NCLOB``. See GH #21 and jazzband/django-silk#255.

Correlated subqueries produce the same numbers with no GROUP BY on the outer
query, so the requests list, the filters and the summary page work on Oracle as
well as on SQLite, MySQL and PostgreSQL.
"""
from django.db.models import (
    Count,
    FloatField,
    IntegerField,
    OuterRef,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce


def _queries_for(model):
    """SQLQuery rows belonging to the outer row of *model*, grouped by that row.

    Requests own their queries through a foreign key; profiles through a
    many-to-many.
    """
    from silk.models import Profile, SQLQuery

    link = 'profiles' if model is Profile else 'request'
    return (
        SQLQuery.objects
        .filter(**{link: OuterRef('pk')})
        .order_by()
        .values(link)
    )


def num_queries_expr(model):
    """Number of SQL queries recorded against each row of *model*.

    Coalesced to 0 so rows without queries sort and filter exactly as they did
    under the old LEFT JOIN + COUNT, which counted them as zero.
    """
    subquery = _queries_for(model).annotate(c=Count('pk')).values('c')[:1]
    return Coalesce(Subquery(subquery, output_field=IntegerField()), 0)


def db_time_expr(model):
    """Total time spent in SQL for each row of *model*.

    Left NULL for rows without queries, matching the old LEFT JOIN + SUM, so
    ``db_time__gte=0`` keeps excluding them.
    """
    subquery = _queries_for(model).annotate(t=Sum('time_taken')).values('t')[:1]
    return Subquery(subquery, output_field=FloatField())
