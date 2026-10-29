import contextlib
import os
from types import SimpleNamespace

from django.test import TestCase

from silk.models import Request
from silk.utils.insights import (
    app_frame,
    parse_frames,
    query_count_test,
    repeat_kind,
    request_insights,
    suggest_fix,
    usual_for,
)

from .factories import RequestMinFactory, SQLQueryFactory


def q(sql):
    return SimpleNamespace(query=sql, time_taken=1.0, traceback='')


TRACEBACK = '''  File "/venv/lib/python3.12/site-packages/django/core/handlers/base.py", line 197, in _get_response
    response = wrapped_callback(request, *callback_args, **callback_kwargs)
  File "/app/shop/views.py", line 74, in product_list
    products = Product.objects.filter(active=True)
  File "/venv/lib/python3.12/site-packages/django/db/models/query.py", line 380, in __iter__
    self._fetch_all()
'''


class TestAppFrame(TestCase):
    def test_picks_innermost_app_frame_with_source_line(self):
        frame = app_frame(TRACEBACK)
        self.assertEqual(frame['file'], '/app/shop/views.py')
        self.assertEqual(frame['line'], 74)
        self.assertEqual(frame['func'], 'product_list')
        self.assertEqual(frame['code'], 'products = Product.objects.filter(active=True)')

    def test_innermost_first_stack_picks_frame_nearest_the_database(self):
        # Silk's middleware stores stacks innermost first; the helper ran the query, not the view.
        stack = '''  File "/venv/lib/python3.12/site-packages/django/db/backends/utils.py", line 100, in execute
    return self.cursor.execute(sql)
  File "/app/shop/helpers.py", line 12, in load_prices
    return list(Price.objects.filter(product=p))
  File "/app/shop/views.py", line 40, in product_list
    prices = load_prices(product)
  File "/venv/lib/python3.12/site-packages/django/core/handlers/base.py", line 197, in _get_response
    response = wrapped_callback(request)
'''
        frame = app_frame(stack)
        self.assertEqual((frame['file'], frame['line']), ('/app/shop/helpers.py', 12))

    def test_no_via_when_app_line_calls_the_orm_directly(self):
        self.assertIsNone(app_frame(TRACEBACK)['via'])

    def test_via_names_the_library_code_that_ran_the_query(self):
        # A pass-through middleware is the nearest app frame; simplejwt actually loads the user.
        stack = '''  File "/venv/lib/python3.12/site-packages/django/db/models/query.py", line 633, in get
    num = len(clone)
  File "/venv/lib/python3.12/site-packages/rest_framework_simplejwt/authentication.py", line 132, in get_user
    user = self.user_model.objects.get(**{api_settings.USER_ID_FIELD: user_id})
  File "/venv/lib/python3.12/site-packages/rest_framework/request.py", line 389, in _authenticate
    user_auth_tuple = authenticator.authenticate(self)
  File "/app/core/middleware.py", line 102, in __call__
    return self.get_response(request)
'''
        frame = app_frame(stack)
        self.assertEqual((frame['file'], frame['line']), ('/app/core/middleware.py', 102))
        self.assertEqual(frame['via']['short'], 'rest_framework_simplejwt/authentication.py')
        self.assertEqual((frame['via']['line'], frame['via']['func']), (132, 'get_user'))

    def test_via_in_outermost_first_stack_is_the_frame_nearest_the_database(self):
        stack = '''  File "/app/shop/views.py", line 20, in order_list
    return render(request, 'orders.html', {'orders': orders})
  File "/venv/lib/python3.12/site-packages/django/template/base.py", line 1040, in render
    return self.render_annotated(context)
  File "/venv/lib/python3.12/site-packages/django/template/base.py", line 895, in _resolve_lookup
    current = getattr(current, bit)
  File "/venv/lib/python3.12/site-packages/django/db/models/fields/related_descriptors.py", line 236, in __get__
    rel_obj = self.get_object(instance)
'''
        via = app_frame(stack)['via']
        self.assertEqual((via['short'], via['line'], via['func']), ('django/template/base.py', 895, '_resolve_lookup'))

    def test_standard_library_frames_are_not_app_code(self):
        # contextlib wraps every view Django calls; a Python outside the venv must not make it "your code".
        stdlib = os.path.realpath(contextlib.__file__)
        stack = TRACEBACK.replace(
            '  File "/app/shop/views.py"',
            f'  File "{stdlib}", line 85, in inner\n    return func(*args, **kwds)\n  File "/app/shop/views.py"')
        self.assertFalse(parse_frames(stack)[1]['app'])
        self.assertEqual(app_frame(stack)['file'], '/app/shop/views.py')

    def test_none_when_only_library_frames(self):
        only_lib = TRACEBACK.replace('/app/shop/views.py', '/venv/lib/python3.12/site-packages/x.py')
        self.assertIsNone(app_frame(only_lib))
        self.assertIsNone(app_frame(''))


class TestRepeatKind(TestCase):
    def test_identical_sql_is_a_duplicate(self):
        self.assertEqual(repeat_kind([q('SELECT 1 FROM t WHERE a = 5')] * 4), 'dup')

    def test_same_shape_different_values_is_n_plus_one(self):
        self.assertEqual(repeat_kind([q(f'SELECT 1 FROM t WHERE a = {i}') for i in range(4)]), 'n1')


class TestSuggestFix(TestCase):
    def test_forward_fk_lookup_suggests_select_related(self):
        group = [q(f'SELECT "shop_product"."id" FROM "shop_product" WHERE "shop_product"."id" = {i}') for i in range(5)]
        code = suggest_fix(group)['code']
        self.assertIn("select_related('product')", code)
        self.assertIn('Product.objects.in_bulk(ids)', code)

    def test_app_label_with_underscores_uses_model_part(self):
        group = [q(f'SELECT "example_app_blind"."name" FROM "example_app_blind" WHERE "example_app_blind"."id" = {i}') for i in range(5)]
        code = suggest_fix(group)['code']
        self.assertIn("select_related('blind')", code)
        self.assertIn('Blind.objects.in_bulk(ids)', code)

    def test_reverse_fk_suggests_prefetch_related(self):
        group = [q(f'SELECT "shop_item"."id" FROM "shop_item" WHERE "shop_item"."order_id" = {i}') for i in range(5)]
        self.assertIn("prefetch_related('item_set')", suggest_fix(group)['code'])

    def test_duplicate_suggests_reuse_or_cache(self):
        fix = suggest_fix([q('SELECT 1 FROM t')] * 3)
        self.assertEqual(fix['kind'], 'dup')
        self.assertIn('cache', fix['code'])


class TestUsualFor(TestCase):
    def test_none_below_minimum_sample(self):
        r = RequestMinFactory(view_name='shop:list', time_taken=100)
        self.assertIsNone(usual_for(r))

    def test_flags_request_well_above_median(self):
        for _ in range(5):
            RequestMinFactory(view_name='shop:list', time_taken=100, num_sql_queries=5)
        slow = RequestMinFactory(view_name='shop:list', time_taken=900, num_sql_queries=40)
        usual = usual_for(slow)
        self.assertEqual(usual['ms'], 100)
        self.assertEqual(usual['queries'], 5)
        self.assertAlmostEqual(usual['slower_x'], 9)
        self.assertEqual(usual['extra_queries'], 35)

    def test_not_flagged_when_close_to_median(self):
        for _ in range(5):
            RequestMinFactory(view_name='shop:list', time_taken=100, num_sql_queries=5)
        normal = RequestMinFactory(view_name='shop:list', time_taken=120, num_sql_queries=6)
        usual = usual_for(normal)
        self.assertEqual(usual['slower_x'], 0)
        self.assertEqual(usual['extra_queries'], 0)


class TestQueryCountTest(TestCase):
    def test_pins_recorded_count_and_notes_target_after_fix(self):
        r = RequestMinFactory(view_name='shop:list', path='/shop/', method='GET', num_sql_queries=12)
        code = query_count_test(r, [{'count': 6}])
        self.assertIn('class ShopListTest(TestCase):', code)
        self.assertIn('with self.assertNumQueries(12):', code)
        self.assertIn("self.client.get('/shop/')", code)
        self.assertIn('expect about 7', code)


class TestRequestInsights(TestCase):
    def test_splits_repeats_and_lists_slowest(self):
        r = RequestMinFactory(time_taken=200)
        for i in range(4):
            SQLQueryFactory(request=r, query=f'SELECT "a_b"."id" FROM "a_b" WHERE "a_b"."id" = {i}', time_taken=10)
        for _ in range(3):
            SQLQueryFactory(request=r, query='SELECT 1 FROM c', time_taken=5)
        queries = list(Request.objects.get(pk=r.pk).queries.all())
        data = request_insights(r, queries)
        self.assertEqual(data['n1_count'], 1)
        self.assertEqual(data['dup_count'], 1)
        self.assertEqual(data['repeat_queries'], 7)
        self.assertEqual(data['db_ms'], 55)
        self.assertEqual(len(data['slowest']), 5)
