from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from silk.config import SilkyConfig
from silk.utils import compare

from .factories import RequestMinFactory, SQLQueryFactory


def request_at(hours_ago, ms, view='shop:list', queries=1):
    r = RequestMinFactory(view_name=view, path='/shop/', start_time=timezone.now() - timedelta(hours=hours_ago))
    r.time_taken = ms
    r.num_sql_queries = queries
    r.save()
    for i in range(queries):
        SQLQueryFactory(request=r, time_taken=2, query=f'SELECT "shop_item"."id" FROM "shop_item" WHERE "shop_item"."id" = {i}')
    return r


class TestCompareRequests(TestCase):
    def test_verdict_and_pattern_diff(self):
        a = request_at(2, 300, queries=5)
        b = request_at(1, 100, queries=1)
        data = compare.compare_requests(a, b)
        self.assertEqual(data['verdict']['headline'], 'B is 67% faster')
        (row,) = data['diff']
        self.assertEqual((row['a'], row['b'], row['kind']), (5, 1, 'fewer'))
        self.assertEqual(row['table'], 'shop_item')

    def test_siblings_step_through_the_endpoint(self):
        old, mid, new = request_at(3, 10), request_at(2, 10), request_at(1, 10)
        request_at(1, 10, view='other:view')
        sib = compare.siblings(mid)
        self.assertEqual((sib['position'], sib['count'], str(sib['older']), str(sib['newer'])), (2, 3, str(old.pk), str(new.pk)))


class TestCompareRanges(TestCase):
    def test_p95_change_and_new_endpoint(self):
        now = timezone.now()
        for _ in range(3):
            request_at(30, 400)
            request_at(5, 200)
        request_at(5, 50, view='shop:new')
        data = compare.compare_ranges((now - timedelta(hours=48), now - timedelta(hours=24)),
                                      (now - timedelta(hours=24), now))
        self.assertEqual(data['verdict']['kind'], 'ok')
        self.assertEqual((data['A']['n'], data['B']['n']), (3, 4))
        kinds = {e['key']: e['kind'] for e in data['endpoints']}
        self.assertEqual(kinds, {'shop:list': '', 'shop:new': 'new'})

    def test_empty_side_says_so(self):
        request_at(1, 100)
        now = timezone.now()
        data = compare.compare_ranges((now - timedelta(days=9), now - timedelta(days=8)), (now - timedelta(hours=2), now))
        self.assertEqual(data['verdict']['headline'], 'Not enough data:')


class TestCompareViews(TestCase):
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

    def test_pages_render(self):
        self.assertContains(self.client.get(reverse('silk:compare')), 'No requests recorded yet')
        a, b = request_at(30, 300), request_at(1, 100)
        self.assertEqual(self.client.get(reverse('silk:compare')).status_code, 200)
        self.assertContains(self.client.get(reverse('silk:compare_pick')), 'shop:list')
        resp = self.client.get(reverse('silk:compare_requests', kwargs={'a_id': a.pk, 'b_id': b.pk}))
        self.assertContains(resp, 'B is 67% faster')
        self.assertContains(self.client.get(reverse('silk:request_detail', kwargs={'request_id': b.pk})), 'Compare with previous')

    def test_reversed_range_falls_back_with_a_message(self):
        request_at(1, 100)
        resp = self.client.get(reverse('silk:compare'), {'a0': '2026-01-02T00:00', 'a1': '2026-01-01T00:00',
                                                         'b0': '2026-01-01T00:00', 'b1': '2026-01-02T00:00'})
        self.assertContains(resp, 'must be before')
