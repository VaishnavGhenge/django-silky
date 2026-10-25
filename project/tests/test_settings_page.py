from django.test import RequestFactory, TestCase
from django.urls import reverse

from silk.config import SilkyConfig
from silk.utils import prefs

from .factories import RequestMinFactory


class TestThresholds(TestCase):
    def test_defaults_and_cookie_values(self):
        rf = RequestFactory()
        self.assertEqual(prefs.thresholds(rf.get('/')), {'slow_ms': 1000, 'ok_ms': 300})
        req = rf.get('/')
        req.COOKIES = {'silky-slow-ms': '500', 'silky-ok-ms': '900'}
        self.assertEqual(prefs.thresholds(req), {'slow_ms': 500, 'ok_ms': 499})
        req.COOKIES = {'silky-slow-ms': 'junk'}
        self.assertEqual(prefs.thresholds(req)['slow_ms'], 1000)

    def test_tier(self):
        th = {'slow_ms': 500, 'ok_ms': 200}
        self.assertEqual([prefs.tier(v, th) for v in (100, 300, 600)], ['good', 'ok', 'bad'])


class TestSettingsPage(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cfg = SilkyConfig()
        cls._saved = (cfg.SILKY_AUTHENTICATION, cfg.SILKY_AUTHORISATION)
        cfg.SILKY_AUTHENTICATION = False
        cfg.SILKY_AUTHORISATION = False

    @classmethod
    def tearDownClass(cls):
        cfg = SilkyConfig()
        cfg.SILKY_AUTHENTICATION, cfg.SILKY_AUTHORISATION = cls._saved
        super().tearDownClass()

    def test_flags_open_access(self):
        resp = self.client.get(reverse('silk:cleardb'))
        self.assertContains(resp, 'can open Silk without logging in')
        self.assertContains(resp, 'SILKY_AUTHENTICATION = True')

    def test_slow_chip_uses_cookie_threshold(self):
        RequestMinFactory()
        self.client.cookies['silky-slow-ms'] = '750'
        self.assertContains(self.client.get(reverse('silk:requests')), 'Slow &gt; 750 ms')

    def test_run_gc_reports_removed_count(self):
        resp = self.client.post(reverse('silk:cleardb'), {'run_gc': '1'})
        self.assertContains(resp, 'Garbage collection removed')
