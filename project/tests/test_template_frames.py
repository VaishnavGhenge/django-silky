import os
import tempfile
from unittest.mock import patch

import jinja2
from django.shortcuts import reverse
from django.template import Context, Engine, Template
from django.test import TestCase

from silk.config import SilkyConfig
from silk.models import SQLQuery
from silk.sql import _stack
from silk.utils.insights import app_frame

from .factories import BlindFactory


class TestQueryFromTemplate(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        BlindFactory.create_batch(size=3)
        SilkyConfig().SILKY_META = False

    def test_query_run_by_a_template_tag_is_blamed_on_the_template_line(self):
        # The view passes a lazy queryset; {% for blind in blinds %} on line 18 runs it.
        self.client.get(reverse('example_app:index'))
        query = SQLQuery.objects.filter(query__contains='example_app_blind').latest('id')
        self.assertTrue(query.code_location.endswith('example_app/templates/example_app/index.html:18'))
        frame = app_frame(query.traceback)
        self.assertEqual(frame['code'], '{% for blind in blinds %}')
        self.assertEqual(frame['via']['short'], 'django/template/defaulttags.py')


class TestTemplateFrames(TestCase):
    def render_capturing_stack(self, engine_or_template, name=None):
        seen = []

        class Customer:
            @property
            def name(self):
                seen.append(_stack())
                return 'Ada'

        context = Context({'orders': [{'customer': Customer()}]})
        template = engine_or_template.get_template(name) if name else engine_or_template
        template.render(context)
        return seen[0]

    def test_innermost_node_comes_first_and_outer_tags_follow(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'orders.html')
            with open(path, 'w') as f:
                f.write('<ul>\n{% for o in orders %}\n  <li>{{  o.customer.name }}</li>\n{% endfor %}\n</ul>\n')
            stack = self.render_capturing_stack(Engine(dirs=[d]), 'orders.html')
        var = '  File "%s", line 3, in template\n    {{ o.customer.name }}\n' % path
        loop = '  File "%s", line 2, in template\n    {%% for o in orders %%}\n' % path
        self.assertIn(var, stack)
        self.assertLess(stack.index(var), stack.index(loop))

    def test_template_without_a_file_adds_no_frame(self):
        stack = self.render_capturing_stack(Template('{% for o in orders %}{{ o.customer.name }}{% endfor %}'))
        self.assertNotIn('in template\n', stack)

    def test_jinja2_frame_shows_the_template_line_not_the_generated_one(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'orders.html')
            with open(path, 'w') as f:
                f.write('<ul>\n{% for o in orders %}\n  <li>{{ o.customer.name }}</li>\n{% endfor %}\n</ul>\n')
            env = jinja2.Environment(loader=jinja2.FileSystemLoader(d))
            seen = []

            class Customer:
                @property
                def name(self):
                    seen.append(_stack())
                    return 'Ada'

            env.get_template('orders.html').render(orders=[{'customer': Customer()}])
        entries = [ln for ln in seen[0].split('\n') if path in ln]
        self.assertEqual(entries, ['  File "%s", line 3, in template' % path])
        self.assertIn('    <li>{{ o.customer.name }}</li>\n', seen[0])

    def test_a_failing_template_node_does_not_break_the_stack(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'orders.html'), 'w') as f:
                f.write('{% for o in orders %}{{ o.customer.name }}{% endfor %}')
            with patch('silk.sql._template_frame', side_effect=AttributeError('token_type')):
                stack = self.render_capturing_stack(Engine(dirs=[d]), 'orders.html')
        self.assertIn('render_annotated', stack)
        self.assertNotIn('in template\n', stack)

    def test_a_failing_jinja2_lookup_falls_back_to_the_plain_frame(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'orders.html'), 'w') as f:
                f.write('{% for o in orders %}{{ o.customer.name }}{% endfor %}')
            env = jinja2.Environment(loader=jinja2.FileSystemLoader(d))
            seen = []

            class Customer:
                @property
                def name(self):
                    seen.append(_stack())
                    return 'Ada'

            with patch('silk.sql._jinja2_frame', side_effect=TypeError('lineno')):
                env.get_template('orders.html').render(orders=[{'customer': Customer()}])
        self.assertIn(', in root\n', seen[0])
