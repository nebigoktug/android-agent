"""Device-free tests: parsing of synthetic uiautomator dumps (no personal data)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phone  # noqa: E402

SETTINGS = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
 <node class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1080,2400]" text="" content-desc="" resource-id="" clickable="false" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false">
  <node class="android.widget.TextView" package="com.android.settings" bounds="[40,100][1040,200]" text="Search settings" content-desc="" resource-id="" clickable="true" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false"/>
  <node class="androidx.recyclerview.widget.RecyclerView" package="com.android.settings" bounds="[0,220][1080,2300]" text="" content-desc="" resource-id="com.android.settings:id/list" clickable="false" scrollable="true" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false">
   <node class="android.widget.LinearLayout" package="com.android.settings" bounds="[0,240][1080,400]" text="" content-desc="" resource-id="" clickable="true" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false">
    <node class="android.widget.TextView" package="com.android.settings" bounds="[40,260][800,320]" text="Wi-Fi" content-desc="" resource-id="" clickable="false" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false"/>
    <node class="android.widget.TextView" package="com.android.settings" bounds="[40,330][800,380]" text="HomeNet" content-desc="" resource-id="" clickable="false" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false"/>
   </node>
   <node class="android.widget.Switch" package="com.android.settings" bounds="[900,420][1040,500]" text="" content-desc="Bluetooth" resource-id="" clickable="true" scrollable="false" checkable="true" checked="true" focused="false" enabled="true" long-clickable="false"/>
   <node class="android.widget.EditText" package="com.android.settings" bounds="[40,520][1040,600]" text="Ağ adı" content-desc="" resource-id="" clickable="true" scrollable="false" checkable="false" checked="false" focused="true" enabled="true" long-clickable="false"/>
   <node class="android.widget.FrameLayout" package="com.android.settings" bounds="[40,2200][140,2290]" text="" content-desc="" resource-id="" clickable="true" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false">
    <node class="android.widget.ImageView" package="com.android.settings" bounds="[60,2210][120,2280]" text="" content-desc="" resource-id="" clickable="false" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false"/>
   </node>
   <node class="android.widget.TextView" package="com.android.settings" bounds="[40,700][1040,800]" text="Line one
line two" content-desc="" resource-id="" clickable="false" scrollable="false" checkable="false" checked="false" focused="false" enabled="true" long-clickable="false"/>
  </node>
 </node>
</hierarchy>"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.items, self.pkg = phone.elements(SETTINGS)
        self.by_label = {e["e"]: e for e in self.items}

    def test_package_and_orientation(self):
        self.assertEqual(self.pkg, "com.android.settings")
        self.assertEqual(phone.ORIENTATION, "portrait")

    def test_text_folds_into_clickable_parent(self):
        self.assertIn("Wi-Fi · HomeNet", self.by_label)
        self.assertNotIn("HomeNet", self.by_label)

    def test_toggle_state(self):
        bt = self.by_label["Bluetooth"]
        self.assertEqual((bt["t"], bt["k"]), ("toggle", "on"))

    def test_focused_unicode_input(self):
        field = self.by_label["Ağ adı"]
        self.assertEqual(field["t"], "input")
        self.assertIn("focused", field["k"])

    def test_scrollable_list(self):
        self.assertTrue(any(e["t"] == "list" for e in self.items))

    def test_unlabeled_icon_gets_position(self):
        self.assertTrue(any(e["e"] == "? icon bottom-left" for e in self.items))

    def test_newlines_collapsed(self):
        self.assertIn("Line one line two", self.by_label)

    def test_tap_center(self):
        e = self.by_label["Search settings"]
        self.assertEqual((e["x"], e["y"]), (540, 150))

    def test_landscape(self):
        phone.elements(SETTINGS.replace('rotation="0"', 'rotation="1"'))
        self.assertEqual(phone.ORIENTATION, "landscape")

    def test_line_format_is_printable(self):
        for i, e in enumerate(self.items):
            line = phone.line(i, e)
            self.assertTrue(line.startswith(f"[{i}] "))
            line.encode("utf-8")

    def test_bad_xml(self):
        self.assertEqual(phone.elements("not xml"), ([], ""))


class McpTests(unittest.TestCase):
    def test_tools_have_schemas(self):
        import mcp_server
        names = {t["name"] for t in mcp_server.TOOLS}
        self.assertTrue({"screen", "tap", "type", "open_app", "open_link"} <= names)
        for t in mcp_server.TOOLS:
            self.assertEqual(t["inputSchema"]["type"], "object")


class MatchTests(unittest.TestCase):
    ITEMS = [{"t": "button", "e": "Wi-Fi · HomeNet"}, {"t": "text", "e": "About Wi-Fi settings"},
             {"t": "toggle", "e": "Bluetooth"}, {"t": "button", "e": "? icon top-left"},
             {"t": "button", "e": "Geliştirici seçenekleri"}]

    def test_punctuation_and_case(self):
        self.assertEqual(phone.match(self.ITEMS, "wifi"), 0)

    def test_turkish_i(self):
        self.assertEqual(phone.match(self.ITEMS, "GELİŞTİRİCİ SEÇENEKLERİ"), 4)
        self.assertEqual(phone.match(self.ITEMS, "gelistirici"), 4)

    def test_exact_beats_substring(self):
        self.assertEqual(phone.match(self.ITEMS, "bluetooth"), 2)

    def test_placeholders_not_matched(self):
        self.assertIsNone(phone.match(self.ITEMS, "icon"))

    def test_no_match(self):
        self.assertIsNone(phone.match(self.ITEMS, "airplane"))


if __name__ == "__main__":
    unittest.main()
