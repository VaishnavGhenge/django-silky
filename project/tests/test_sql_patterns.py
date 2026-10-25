from urllib.parse import urlencode

from django.test import TestCase
from django.urls import reverse

from silk.config import SilkyConfig
from silk.models import SQLQuery
from silk.utils import sql_patterns
from silk.utils.n_plus_one import pattern_hash

from .factories import RequestMinFactory, SQLQueryFactory

# Innermost first, as Silk's middleware records stacks.
STACK = '''  File "/venv/lib/python3.12/site-packages/django/db/backends/utils.py", line 100, in execute
    return self.cursor.execute(sql)
  File "/app/shop/views.py", line 79, in product_list
    names.append(Product.objects.get(pk=p.pk).name)
  File "/venv/lib/python3.12/site-packages/django/core/handlers/base.py", line 197, in _get_response
    response = wrapped_callback(request)
'''


def record_loop(request, n=4):
    for i in range(n):
        SQLQueryFactory(request=request, traceback=STACK, time_taken=2,
                        query=f'SELECT "shop_product"."name" FROM "shop_product" WHERE "shop_product"."id" = {i}')


class TestFieldsFilledOnSave(TestCase):
    def test_pattern_hash_and_location_set_on_save(self):
        q = SQLQueryFactory(request=RequestMinFactory(), traceback=STACK, query='SELECT 1 FROM t WHERE a = 5')
        self.assertEqual(q.pattern_hash, pattern_hash('SELECT 1 FROM t WHERE a = 7'))
        self.assertEqual(q.code_location, '/app/shop/views.py:79')

    def test_bulk_create_fills_fields_too(self):
        r = RequestMinFactory()
        SQLQuery.objects.bulk_create([SQLQuery(request=r, query='SELECT 2 FROM u', traceback=STACK)])
        q = SQLQuery.objects.get(request=r)
        self.assertTrue(q.pattern_hash)
        self.assertEqual(q.code_location, '/app/shop/views.py:79')


class TestAggregation(TestCase):
    def test_same_shape_groups_and_repeats_are_flagged(self):
        record_loop(RequestMinFactory(), n=4)
        SQLQueryFactory(request=RequestMinFactory(), traceback=STACK, query='SELECT COUNT(*) FROM "shop_order"')
        rows = {p['table']: p for p in sql_patterns.patterns()}
        self.assertEqual(rows['shop_product']['calls'], 4)
        self.assertEqual(rows['shop_product']['repeats'], 1)
        self.assertEqual(rows['shop_order']['repeats'], 0)

    def test_hotspot_marks_a_line_that_runs_in_a_loop(self):
        record_loop(RequestMinFactory(), n=4)
        (row,) = sql_patterns.hotspots()
        self.assertEqual((row['file'], row['line']), ('/app/shop/views.py', 79))
        self.assertEqual(row['calls'], 4)
        self.assertEqual(row['repeats'], 1)

    def test_pattern_detail_includes_fix_for_repeats(self):
        record_loop(RequestMinFactory(), n=4)
        p = sql_patterns.patterns()[0]
        detail = sql_patterns.pattern_detail(p['pattern_hash'])
        self.assertEqual(detail['fix']['kind'], 'n1')
        self.assertIn("select_related('product')", detail['fix']['code'])
        self.assertEqual(detail['frame']['line'], 79)


class TestViews(TestCase):
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

    def setUp(self):
        record_loop(RequestMinFactory(), n=4)

    def test_sql_page_and_panel_render(self):
        self.assertEqual(self.client.get(reverse('silk:sql')).status_code, 200)
        h = SQLQuery.objects.values_list('pattern_hash', flat=True).first()
        resp = self.client.get(reverse('silk:sql') + f'?p={h}')
        self.assertContains(resp, 'Likely fix')

    def test_sql_page_returns_fragment_to_htmx(self):
        resp = self.client.get(reverse('silk:sql'), HTTP_HX_REQUEST='true')
        self.assertContains(resp, 'id="split"')
        self.assertNotContains(resp, '<html')

    def test_hotspots_page_and_panel_render(self):
        self.assertEqual(self.client.get(reverse('silk:hotspots')).status_code, 200)
        resp = self.client.get(reverse('silk:hotspots') + '?' + urlencode({'loc': '/app/shop/views.py:79'}))
        self.assertContains(resp, 'views.py:79')

    def test_unknown_pattern_shows_list_without_panel(self):
        resp = self.client.get(reverse('silk:sql') + '?p=nope')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Pattern detail')
