"""Oracle stores TextField columns as NCLOB and refuses to GROUP BY a LOB
(ORA-00932). Django only collapses a model-wide GROUP BY down to the primary
key on PostgreSQL, so any ``Request.objects.annotate(Sum(...))`` over whole rows
breaks the summary page, the requests list and the query-count filters on
Oracle. These tests run on SQLite (which tolerates the wide GROUP BY) and assert
on the generated SQL instead, so they fail on the old queries without needing an
Oracle instance.

See GH #21 and jazzband/django-silk#255.
"""
import re

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from silk import models
from silk.middleware import silky_reverse
from silk.request_filters import NumQueriesFilter, TimeSpentOnQueriesFilter
from silk.views.requests import RequestsView
from silk.views.summary import SummaryView

from .test_lib.mock_suite import MockSuite

mock_suite = MockSuite()

# TextField on Request/SQLQuery/Response, i.e. NCLOB once Oracle creates the table.
LOB_COLUMNS = (
    'query_params',
    'raw_body',
    'body',
    'encoded_headers',
    'pyprofile',
    'traceback',
    'analysis',
)

GROUP_BY = re.compile(r'GROUP BY (.*?)(?: HAVING| ORDER BY| LIMIT|$)', re.IGNORECASE | re.DOTALL)


def lob_group_by_columns(sql):
    """Names of LOB columns this statement groups by, if any."""
    found = []
    for clause in GROUP_BY.findall(sql):
        found.extend(column for column in LOB_COLUMNS if f'"{column}"' in clause)
    return found


class LOBGroupByMixin:
    def assertNoLOBGroupBy(self, sql):
        columns = lob_group_by_columns(sql)
        self.assertEqual(
            columns, [],
            'GROUP BY names LOB column(s) %s, which Oracle rejects with '
            'ORA-00932:\n%s' % (', '.join(columns), sql),
        )

    def assertQuerysetSafe(self, queryset):
        self.assertNoLOBGroupBy(str(queryset.query))

    def assertViewSafe(self, url):
        """Fetch *url* and check every statement it actually ran."""
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(captured.captured_queries), 0)
        for query in captured.captured_queries:
            self.assertNoLOBGroupBy(query['sql'])


class TestFilterSQL(LOBGroupByMixin, TestCase):
    def test_num_queries_filter_on_requests(self):
        query_set = NumQueriesFilter(2).contribute_to_query_set(models.Request.objects.all())
        self.assertQuerysetSafe(query_set.filter(num_queries__gte=2))

    def test_num_queries_filter_on_profiles(self):
        query_set = NumQueriesFilter(2).contribute_to_query_set(models.Profile.objects.all())
        self.assertQuerysetSafe(query_set.filter(num_queries__gte=2))

    def test_db_time_filter_on_requests(self):
        query_set = TimeSpentOnQueriesFilter(2).contribute_to_query_set(models.Request.objects.all())
        self.assertQuerysetSafe(query_set.filter(db_time__gte=2))

    def test_requests_sorted_by_db_time(self):
        self.assertQuerysetSafe(RequestsView()._get_objects(show=None, order_by='db_time'))


class TestViewSQL(LOBGroupByMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        # Two requests against the same view so the summary's per-view
        # "worst offender" lookups have something to rank.
        for _ in range(3):
            request = mock_suite.mock_request()
            request.view_name = 'app:index'
            request.save()
            mock_suite.mock_sql_queries(request=request, n=3)

    def test_summary_page(self):
        self.assertViewSafe(silky_reverse('summary'))

    def test_requests_page(self):
        self.assertViewSafe(silky_reverse('requests'))

    def test_summary_context_builds(self):
        """The per-view lookups still return Requests carrying their total."""
        view = SummaryView()
        by_db_time = view._time_spent_in_db_by_view([])
        by_num_queries = view._num_queries_by_view([])
        self.assertTrue(by_db_time)
        self.assertTrue(by_num_queries)
        for request in by_db_time:
            self.assertIsInstance(request, models.Request)
            self.assertIsNotNone(request.t)
        for request in by_num_queries:
            self.assertIsInstance(request, models.Request)
            self.assertGreaterEqual(request.t, 0)


class TestAggregatesUnchanged(LOBGroupByMixin, TestCase):
    """The rewritten aggregates must return what the old ones returned."""

    @classmethod
    def setUpTestData(cls):
        cls.requests = []
        for n in (0, 2, 5):
            request = mock_suite.mock_request()
            models.SQLQuery.objects.filter(request=request).delete()
            request.refresh_from_db()
            if n:
                mock_suite.mock_sql_queries(request=request, n=n)
            cls.requests.append(request)

    def test_avg_num_queries_counts_requests_without_queries(self):
        view = SummaryView()
        expected = sum(
            models.SQLQuery.objects.filter(request=r).count() for r in self.requests
        ) / len(self.requests)
        self.assertAlmostEqual(view._avg_num_queries([]), expected)

    def test_avg_time_spent_on_queries_skips_requests_without_queries(self):
        view = SummaryView()
        totals = []
        for request in self.requests:
            times = list(
                models.SQLQuery.objects.filter(request=request)
                .values_list('time_taken', flat=True)
            )
            if times:
                totals.append(sum(times))
        self.assertAlmostEqual(view._avg_time_spent_on_queries([]), sum(totals) / len(totals))

    def test_avg_overall_time(self):
        view = SummaryView()
        times = [r.time_taken for r in self.requests if r.time_taken is not None]
        self.assertAlmostEqual(view._avg_overall_time([]), sum(times) / len(times))

    def test_num_queries_filter_matches_row_counts(self):
        query_set = NumQueriesFilter(2).contribute_to_query_set(models.Request.objects.all())
        matched = set(query_set.filter(num_queries__gte=2).values_list('pk', flat=True))
        expected = {
            r.pk for r in self.requests
            if models.SQLQuery.objects.filter(request=r).count() >= 2
        }
        self.assertEqual(matched, expected)

    def test_db_time_filter_excludes_requests_without_queries(self):
        query_set = TimeSpentOnQueriesFilter(0).contribute_to_query_set(models.Request.objects.all())
        matched = set(query_set.filter(db_time__gte=0).values_list('pk', flat=True))
        expected = {
            r.pk for r in self.requests
            if models.SQLQuery.objects.filter(request=r).exists()
        }
        self.assertEqual(matched, expected)
