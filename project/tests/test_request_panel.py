from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from silk.config import SilkyConfig
from silk.views.request_detail import panel_sql

from .factories import RequestMinFactory, SQLQueryFactory


def record(request, offsets_ms, query='SELECT "shop_item"."id" FROM "shop_item" WHERE "shop_item"."id" = {i}'):
    out = []
    for i, offset in enumerate(offsets_ms):
        start = request.start_time + timedelta(milliseconds=offset)
        out.append(SQLQueryFactory(request=request, query=query.format(i=i), time_taken=10,
                                   start_time=start, end_time=start + timedelta(milliseconds=10)))
    return out


class TestPanelSql(TestCase):
    def setUp(self):
        self.request = RequestMinFactory(start_time=timezone.now(), time_taken=200)

    def test_bars_sit_where_each_query_ran(self):
        queries = record(self.request, [0, 100, 150])
        sql = panel_sql(self.request, queries, set(), 3)
        self.assertTrue(sql['timeline'])
        self.assertEqual([r['left'] for r in sql['rows']], [0, 50, 75])
        self.assertEqual([r['width'] for r in sql['rows']], [5, 5, 5])

    def test_start_times_outside_the_request_fall_back_to_durations(self):
        queries = record(self.request, [0, -86_400_000])
        sql = panel_sql(self.request, queries, set(), 3)
        self.assertFalse(sql['timeline'])
        self.assertEqual([r['left'] for r in sql['rows']], [0, 0])

    def test_groups_by_shape_and_marks_repeats(self):
        queries = record(self.request, [0, 10, 20]) + record(self.request, [30], query='SELECT 1')
        sql = panel_sql(self.request, queries, {q.pk for q in queries[:3]}, 3)
        self.assertEqual([(g['n'], g['repeated']) for g in sql['groups']], [(3, True), (1, False)])
        self.assertEqual([r['repeated'] for r in sql['rows']], [True, True, True, False])


class TestPanelView(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cfg = SilkyConfig()
        cls._auth = (cfg.SILKY_AUTHENTICATION, cfg.SILKY_AUTHORISATION)
        cfg.SILKY_AUTHENTICATION = False
        cfg.SILKY_AUTHORISATION = False

    @classmethod
    def tearDownClass(cls):
        cfg = SilkyConfig()
        cfg.SILKY_AUTHENTICATION, cfg.SILKY_AUTHORISATION = cls._auth
        super().tearDownClass()

    def test_panel_sql_tab_has_timeline_and_grouped_views(self):
        req = RequestMinFactory(start_time=timezone.now(), time_taken=200, num_sql_queries=3)
        record(req, [0, 10, 20])
        resp = self.client.get(reverse('silk:request_detail', args=[req.pk]), HTTP_HX_REQUEST='true')
        self.assertContains(resp, 'data-sql-pane="timeline"')
        self.assertContains(resp, 'data-sql-pane="grouped"')
        self.assertContains(resp, 'Possible N+1')

    def test_sql_page_shows_offsets_and_hides_impossible_ones(self):
        req = RequestMinFactory(start_time=timezone.now(), time_taken=200, num_sql_queries=2)
        record(req, [12, -86_400_000])
        resp = self.client.get(reverse('silk:request_sql', args=[req.pk]))
        self.assertContains(resp, '+12 ms')
        self.assertContains(resp, 'Start time falls outside the request')
        self.assertNotContains(resp, 'day,')
