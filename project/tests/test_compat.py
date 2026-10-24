import json
from unittest.mock import Mock

from django.test import TestCase

from silk.model_factory import ResponseModelFactory

DJANGO_META_CONTENT_TYPE = 'CONTENT_TYPE'
HTTP_CONTENT_TYPE = 'content-type'


class TestByteStringCompatForResponse(TestCase):

    def test_bytes_compat(self):
        """
        Test ResponseModelFactory formats json with bytes content
        """
        mock = Mock()
        mock.headers = {HTTP_CONTENT_TYPE: 'application/json;'}
        d = {'k': 'v'}
        mock.content = bytes(json.dumps(d), 'utf-8')
        mock.get = mock.headers.get
        factory = ResponseModelFactory(mock)
        body, content = factory.body()
        self.assertDictEqual(json.loads(body), d)


class TestPackageVersion(TestCase):
    def test_version_falls_back_when_metadata_is_missing(self):
        import importlib
        import importlib.metadata
        from unittest.mock import patch

        import silk

        self.addCleanup(importlib.reload, silk)
        with patch(
            "importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError,
        ):
            importlib.reload(silk)

        self.assertEqual(silk.__version__, "unknown")
