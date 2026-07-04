from django.test import TestCase

from silk import models
from silk.middleware import silky_reverse
from silk.views.summary import SummaryView, _bucket_counts, _percentiles

from .factories import RequestMinFactory
from .test_lib.assertion import dict_contains
from .test_lib.mock_suite import MockSuite

mock_suite = MockSuite()


class TestSummaryView(TestCase):
    def test_longest_query_by_view(self):
        [mock_suite.mock_request() for _ in range(0, 10)]
        print([x.time_taken for x in SummaryView()._longest_query_by_view([])])

    def test_view_without_session_and_auth_middlewares(self):
        """
        Filters are not present because there is no `session` to store them.
        """
        with self.modify_settings(MIDDLEWARE={
            'remove': [
                'django.contrib.sessions.middleware.SessionMiddleware',
                'django.contrib.auth.middleware.AuthenticationMiddleware',
                'django.contrib.messages.middleware.MessageMiddleware',
            ],
        }):
            # test filters on POST
            seconds = 3600
            response = self.client.post(silky_reverse('summary'), {
                'filter-seconds-value': seconds,
                'filter-seconds-typ': 'SecondsFilter',
            })
            context = response.context
            self.assertTrue(dict_contains({
                'filters': {
                    'seconds': {'typ': 'SecondsFilter', 'value': seconds, 'str': f'>{seconds} seconds ago'}
                }
            }, context))


class TestPercentiles(TestCase):

    def test_empty_queryset_returns_zeros(self):
        result = _percentiles(models.Request.objects.all(), 'time_taken')
        self.assertEqual(result, {25: 0.0, 50: 0.0, 75: 0.0, 95: 0.0, 99: 0.0})

    def test_single_value(self):
        RequestMinFactory.create(time_taken=100.0)
        result = _percentiles(models.Request.objects.all(), 'time_taken')
        self.assertEqual(result, {25: 100.0, 50: 100.0, 75: 100.0, 95: 100.0, 99: 100.0})

    def test_linear_interpolation(self):
        for t in [10.0, 20.0, 30.0, 40.0]:
            RequestMinFactory.create(time_taken=t)
        result = _percentiles(models.Request.objects.all(), 'time_taken')
        # n=4: idx = p/100 * 3
        self.assertEqual(result[25], 17.5)
        self.assertEqual(result[50], 25.0)
        self.assertEqual(result[75], 32.5)
        self.assertEqual(result[95], 38.5)
        self.assertEqual(result[99], 39.7)

    def test_does_not_materialise_all_values(self):
        for t in range(20):
            RequestMinFactory.create(time_taken=float(t))
        # 1 COUNT + one two-row slice per percentile
        with self.assertNumQueries(6):
            _percentiles(models.Request.objects.all(), 'time_taken')


class TestSummaryAggregates(TestCase):

    def test_response_time_histogram_buckets(self):
        for t in [10.0, 60.0, 150.0, 300.0, 700.0, 2000.0, 2500.0]:
            RequestMinFactory.create(time_taken=t)
        result = SummaryView()._response_time_histogram([])
        self.assertEqual(
            [(b['label'], b['count']) for b in result],
            [('<50ms', 1), ('50-100ms', 1), ('100-200ms', 1),
             ('200-500ms', 1), ('500ms-1s', 1), ('>1s', 2)],
        )

    def test_query_count_histogram_buckets(self):
        for n in [0, 3, 8, 15, 30, 60]:
            RequestMinFactory.create(num_sql_queries=n)
        result = SummaryView()._query_count_histogram([])
        self.assertEqual(
            [(b['label'], b['count']) for b in result],
            [('0', 1), ('1–5', 1), ('6–10', 1), ('11–25', 1), ('26–50', 1), ('>50', 1)],
        )

    def test_histograms_are_single_queries(self):
        RequestMinFactory.create(time_taken=10.0)
        view = SummaryView()
        with self.assertNumQueries(1):
            view._response_time_histogram([])
        with self.assertNumQueries(1):
            view._query_count_histogram([])

    def test_status_distribution(self):
        for status in [200, 201, 301, 404, 500]:
            request = RequestMinFactory.create()
            models.Response.objects.create(request=request, status_code=status)
        result = SummaryView()._status_distribution([])
        self.assertEqual(result, {'2xx': 2, '3xx': 1, '4xx': 1, '5xx': 1})

    def test_sql_time_percentiles_empty(self):
        result = SummaryView()._sql_time_percentiles([])
        self.assertEqual(result, {25: 0.0, 50: 0.0, 75: 0.0, 95: 0.0, 99: 0.0})
