import json
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from example_app.models import Blind
from silk.management.commands.silk_seed import APP_ROOT
from silk.models import Profile, Request, SQLQuery
from silk.utils.insights import app_frame, repeat_kind
from silk.utils.n_plus_one import detect_n_plus_one


class TestSeedCommand(TestCase):
    def seed(self, **options):
        call_command("silk_seed", stdout=StringIO(), **options)

    @freeze_time("2026-10-25T12:00:00Z")
    def test_traffic_is_consistent(self):
        self.seed(requests=400, days=7, seed=42)
        self.assertEqual(Request.objects.count(), 400)
        now = timezone.now()
        statuses = []
        for request in Request.objects.select_related("response"):
            self.assertGreaterEqual(request.start_time, now - timedelta(days=7))
            self.assertLessEqual(request.end_time, now)
            self.assertNotIn("?", request.path)
            self.assertTrue(request.view_name)
            self.assertAlmostEqual(request.time_taken, (request.end_time - request.start_time).total_seconds() * 1000)
            queries = list(request.queries.order_by("start_time"))
            self.assertEqual(request.num_sql_queries, len(queries))
            self.assertLess(sum(q.time_taken for q in queries), request.time_taken)
            previous_end = request.start_time
            for query in queries:
                self.assertGreaterEqual(query.start_time, previous_end)
                self.assertLessEqual(query.end_time, request.end_time)
                self.assertNotRegex(query.query, r"%s\b")
                frame = app_frame(query.traceback)
                if frame:
                    self.assertTrue(frame["file"].startswith(str(APP_ROOT)))
                    self.assertEqual(query.code_location, f'{frame["file"]}:{frame["line"]}')
                previous_end = query.end_time
            response = request.response
            statuses.append(response.status_code)
            if request.method == "GET":
                self.assertEqual(request.body, "")
            if request.query_params:
                self.assertTrue(all(isinstance(v, str) for v in json.loads(request.query_params).values()))
            if response.content_type == "application/json":
                payload = json.loads(response.body)
                if "results" in payload and "count" in payload and request.view_name == "catalog:search":
                    self.assertEqual(payload["count"], len(payload["results"]))
        self.assertGreater(sum(s < 400 for s in statuses), 0.9 * len(statuses))
        for status in (201, 400, 401, 404):
            self.assertIn(status, statuses)
        # Hot paths name an app line; session lookups happen inside Django and do not.
        self.assertTrue(SQLQuery.objects.exclude(code_location="").exists())
        self.assertTrue(SQLQuery.objects.filter(code_location="").exists())
        self.assertTrue(Request.objects.exclude(pyprofile="").exists())
        self.assertTrue(Profile.objects.exists())
        for profile in Profile.objects.select_related("request"):
            self.assertGreaterEqual(profile.start_time, profile.request.start_time)
            self.assertLessEqual(profile.end_time, profile.request.end_time)
            for query in profile.queries.all():
                self.assertEqual(query.request_id, profile.request_id)
                self.assertGreaterEqual(query.start_time, profile.start_time)
                self.assertLessEqual(query.end_time, profile.end_time)

    def kinds(self, view_name):
        request = Request.objects.filter(view_name=view_name, num_sql_queries__gt=6).first()
        return {repeat_kind(g.queries) for g in detect_n_plus_one(list(request.queries.all())).groups}

    def test_known_query_problems_are_detectable(self):
        self.seed(requests=600, seed=42)
        self.assertIn("n1", self.kinds("orders:order_list"))
        self.assertIn("n1", self.kinds("admin:orders_order_changelist"))
        self.assertIn("dup", self.kinds("catalog:product_detail"))

    def test_server_errors_are_recorded(self):
        self.seed(requests=1500, seed=42)
        self.assertTrue(Request.objects.filter(response__status_code=500).exists())
        self.assertTrue(Profile.objects.filter(exception_raised=True).exists())

    def test_clear_replaces_logs_and_keeps_application_data(self):
        existing = Blind.objects.create(name="Customer's existing blind", child_safe=True)
        self.seed(requests=10, days=1, seed=42)
        self.seed(requests=3, days=1, seed=7, clear=True)
        self.assertEqual(Request.objects.count(), 3)
        self.assertTrue(Blind.objects.filter(pk=existing.pk).exists())
        self.assertFalse(SQLQuery.objects.filter(request__isnull=True).exists())
        self.assertFalse(Profile.objects.filter(request__isnull=True).exists())
        self.seed(requests=2, days=1, seed=3)
        self.assertEqual(Request.objects.count(), 5)

    def test_invalid_arguments_do_not_clear_existing_data(self):
        self.seed(requests=1, days=1, seed=42)
        for options in ({"requests": -1}, {"days": 0}, {"days": -2}):
            with self.assertRaises(CommandError):
                self.seed(clear=True, **options)
            self.assertEqual(Request.objects.count(), 1)

    def test_zero_requests_can_clear_logs(self):
        self.seed(requests=1, seed=42)
        self.seed(requests=0, clear=True)
        self.assertFalse(Request.objects.exists())

    @freeze_time("2026-10-25T12:00:00Z")
    def test_same_seed_gives_same_traffic(self):
        def traffic():
            return list(Request.objects.order_by("start_time").values_list(
                "start_time", "path", "response__status_code", "num_sql_queries"))
        self.seed(requests=100, seed=42)
        first = traffic()
        self.seed(requests=100, seed=42, clear=True)
        self.assertEqual(traffic(), first)
