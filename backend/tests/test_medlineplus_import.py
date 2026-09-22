import unittest
from datetime import date

from medical.import_medlineplus import TOPICS, build_documents, summary_text
from xml.etree import ElementTree as ET


class MedlinePlusImportTests(unittest.TestCase):
    def test_summary_preserves_list_items(self):
        element = ET.fromstring("<full-summary><p>Seek help if:</p><ul><li>Severe pain</li><li>Fainting</li></ul></full-summary>")
        self.assertEqual(summary_text(element), "Seek help if:\n- Severe pain\n- Fainting")

    def test_summary_decodes_escaped_medlineplus_markup(self):
        element = ET.fromstring("<full-summary>&lt;p&gt;Rest&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Drink water&lt;/li&gt;&lt;/ul&gt;</full-summary>")
        self.assertEqual(summary_text(element), "Rest\n- Drink water")

    def test_import_requires_every_pinned_topic(self):
        topic_id = next(iter(TOPICS))
        xml = (
            '<health-topics date-generated="09/19/2026 00:00:00">'
            f'<health-topic id="{topic_id}" language="English" title="Example" url="https://example.org/topic">'
            '<full-summary><p>' + ('safe patient information ' * 10) + '</p></full-summary>'
            '</health-topic></health-topics>'
        ).encode()
        with self.assertRaisesRegex(ValueError, "missing pinned MedlinePlus topics"):
            build_documents(xml, date(2026, 9, 22))


if __name__ == "__main__":
    unittest.main()
