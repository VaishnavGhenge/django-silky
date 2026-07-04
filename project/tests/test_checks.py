from django.test import TestCase

from silk.checks import check_garbage_collect_settings
from silk.config import SilkyConfig


class CheckGarbageCollectSettingsTest(TestCase):

    def setUp(self):
        self.gc_mode = SilkyConfig().SILKY_GARBAGE_COLLECT_MODE
        self.max_time = SilkyConfig().SILKY_MAX_RECORDED_TIME

    def tearDown(self):
        SilkyConfig().SILKY_GARBAGE_COLLECT_MODE = self.gc_mode
        SilkyConfig().SILKY_MAX_RECORDED_TIME = self.max_time

    def test_default_config_passes(self):
        self.assertEqual(check_garbage_collect_settings(None), [])

    def test_valid_time_config_passes(self):
        SilkyConfig().SILKY_GARBAGE_COLLECT_MODE = 'time'
        SilkyConfig().SILKY_MAX_RECORDED_TIME = 60
        self.assertEqual(check_garbage_collect_settings(None), [])

    def test_unknown_mode_is_an_error(self):
        SilkyConfig().SILKY_GARBAGE_COLLECT_MODE = 'Count'
        ids = [e.id for e in check_garbage_collect_settings(None)]
        self.assertIn('silk.E001', ids)

    def test_negative_max_time_is_an_error(self):
        SilkyConfig().SILKY_GARBAGE_COLLECT_MODE = 'time'
        SilkyConfig().SILKY_MAX_RECORDED_TIME = -5
        ids = [e.id for e in check_garbage_collect_settings(None)]
        self.assertIn('silk.E002', ids)

    def test_non_integer_max_time_is_an_error(self):
        SilkyConfig().SILKY_MAX_RECORDED_TIME = '60'
        ids = [e.id for e in check_garbage_collect_settings(None)]
        self.assertIn('silk.E002', ids)

    def test_time_mode_without_window_is_a_warning(self):
        SilkyConfig().SILKY_GARBAGE_COLLECT_MODE = 'time'
        SilkyConfig().SILKY_MAX_RECORDED_TIME = None
        ids = [e.id for e in check_garbage_collect_settings(None)]
        self.assertEqual(ids, ['silk.W001'])
