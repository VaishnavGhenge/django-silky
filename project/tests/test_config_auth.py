from django.contrib.auth.models import User
from django.test import TestCase

from silk.config import SilkyConfig, default_permissions
from silk.middleware import silky_reverse


class TestAuth(TestCase):
    def test_authentication(self):
        SilkyConfig().SILKY_AUTHENTICATION = True
        response = self.client.get(silky_reverse('requests'))
        self.assertEqual(response.status_code, 302)

    def test_default_authorisation(self):
        SilkyConfig().SILKY_AUTHENTICATION = True
        SilkyConfig().SILKY_AUTHORISATION = True
        SilkyConfig().SILKY_PERMISSIONS = default_permissions
        username_and_password = 'bob'  # bob is an imbecile and uses the same pass as his username
        user = User.objects.create(username=username_and_password)
        user.set_password(username_and_password)
        user.save()
        self.client.login(username=username_and_password, password=username_and_password)
        response = self.client.get(silky_reverse('requests'))
        self.assertEqual(response.status_code, 404)
        user.is_staff = True
        user.save()
        response = self.client.get(silky_reverse('requests'))
        self.assertEqual(response.status_code, 200)

    def test_custom_authorisation(self):
        SilkyConfig().SILKY_AUTHENTICATION = True
        SilkyConfig().SILKY_AUTHORISATION = True

        def custom_authorisation(user):
            return user.username.startswith('mike')

        SilkyConfig().SILKY_PERMISSIONS = custom_authorisation
        username_and_password = 'bob'  # bob is an imbecile and uses the same pass as his username
        user = User.objects.create(username=username_and_password)
        user.set_password(username_and_password)
        user.save()
        self.client.login(username=username_and_password, password=username_and_password)
        response = self.client.get(silky_reverse('requests'))
        self.assertEqual(response.status_code, 404)
        user.username = 'mike2'
        user.save()
        response = self.client.get(silky_reverse('requests'))
        self.assertEqual(response.status_code, 200)

    def test_config_defaults_are_secure(self):
        """The class-level defaults dict should ship with both auth flags True."""
        self.assertIs(SilkyConfig.defaults['SILKY_AUTHENTICATION'], True)
        self.assertIs(SilkyConfig.defaults['SILKY_AUTHORISATION'], True)

    def test_anonymous_request_redirects_to_login_under_secure_defaults(self):
        """Anonymous access with auth enabled must redirect to login, not 404."""
        SilkyConfig().SILKY_AUTHENTICATION = True
        SilkyConfig().SILKY_AUTHORISATION = True
        response = self.client.get(silky_reverse('requests'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('next=', response['Location'])
