import unittest

from markup import markup


class MarkupTests(unittest.TestCase):
    def test_dynamic_tags_and_entities_remain_literal_text(self):
        title = '<b>North & South</b> "quoted" \'text\''
        self.assertEqual(
            markup(t"<b>{title}</b>"),
            '<b>&lt;b&gt;North &amp; South&lt;/b&gt; &quot;quoted&quot; &#x27;text&#x27;</b>',
        )

    def test_formatting_and_conversion_happen_before_escaping(self):
        price = 1.234
        label = "<rate>"
        self.assertEqual(
            markup(t"<b>{price:.2f}</b> {label!r}"),
            "<b>1.23</b> &#x27;&lt;rate&gt;&#x27;",
        )

    def test_adjacent_values_and_empty_text(self):
        first, second = "<&", ">"
        self.assertEqual(markup(t"{first}{second}"), "&lt;&amp;&gt;")
        self.assertEqual(markup(t""), "")
        self.assertEqual(markup(t"<b>Static</b>"), "<b>Static</b>")
