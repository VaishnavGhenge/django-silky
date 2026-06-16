import datetime

from django.core import management
from django.test import TestCase
from freezegun import freeze_time

from silk import models
from silk.config import SilkyConfig

from .factories import RequestMinFactory


class TestViewClearDB(TestCase):
    def setUp(self):
        self.gc_mode = SilkyConfig().SILKY_GARBAGE_COLLECT_MODE
        self.max_time = SilkyConfig().SILKY_MAX_RECORDED_TIME

    def tearDown(self):
        SilkyConfig().SILKY_GARBAGE_COLLECT_MODE = self.gc_mode
        SilkyConfig().SILKY_MAX_RECORDED_TIME = self.max_time

    def test_garbage_collect_command(self):
        SilkyConfig().SILKY_MAX_RECORDED_REQUESTS = 2
        RequestMinFactory.create_batch(3)
        self.assertEqual(models.Request.objects.count(), 3)
        management.call_command("silk_request_garbage_collect")
        self.assertEqual(models.Request.objects.count(), 2)
        management.call_command("silk_request_garbage_collect", max_requests=1)
        self.assertEqual(models.Request.objects.count(), 1)
        management.call_command(
            "silk_request_garbage_collect", max_requests=0, verbosity=2
        )
        self.assertEqual(models.Request.objects.count(), 0)

    def test_garbage_collect_command_time_mode(self):
        now = datetime.datetime(2016, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        old = RequestMinFactory.create(start_time=now - datetime.timedelta(minutes=120))
        recent = RequestMinFactory.create(start_time=now - datetime.timedelta(minutes=5))
        with freeze_time(now):
            management.call_command(
                "silk_request_garbage_collect", mode="time", max_time=60
            )
        self.assertFalse(models.Request.objects.filter(id=old.id).exists())
        self.assertTrue(models.Request.objects.filter(id=recent.id).exists())
