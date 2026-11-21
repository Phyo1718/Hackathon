import re
import unittest

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src import ui_theme


class ThemeCssTests(unittest.TestCase):
    def test_css_has_no_tag_like_text(self):
        # st.html sanitises with DOMPurify, which drops a whole <style> block whose text contains
        # something like "<a>" (even inside a CSS comment): the app would lose its entire theme.
        css = ui_theme.css()
        body = css[len("<style>"):-len("</style>")]
        self.assertTrue(css.startswith("<style>") and css.endswith("</style>"))
        self.assertIsNone(re.search(r"<[/!a-zA-Z]", body), "tag-like text in the theme CSS")

    def test_filled_buttons_force_white_text(self):
        css = ui_theme.css()
        rule = re.search(r'\.stApp :is\(\[data-testid="stBaseButton-primary"\], \[data-testid="stBaseLinkButton-primary"\]\)'
                         r"[^{]*:visited[^{]*\{\s*color: #FFFFFF !important;", css)
        self.assertIsNotNone(rule)


if __name__ == "__main__":
    unittest.main()
