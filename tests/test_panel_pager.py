"""The panel's pager arithmetic, on CPython.

Three screens page their lists because the RGB panel forbids scrolling, and an
item that does not fit is lost in silence. How many items fit is a question only
the board can answer (products/panel/hwtest/hwtest_ui.py measures it); how the
pager behaves once that number is known is pure arithmetic, and belongs here
where it can be exhaustive and fast.

The interesting half is clamp_page. _rebuild runs on every store write, and the
device poll writes every three seconds, so the page index is re-derived
constantly while the user is reading. It has to survive that.

The path insert is only for ``pager`` -- the panel's device modules live at the
board root rather than in the installed package. It imports no LVGL, which is
what makes running it here possible.
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "products", "panel", "device"),
)

import pager  # noqa: E402  (needs the path insert above)


class PageCountTests(unittest.TestCase):
    def test_an_empty_list_is_still_one_page(self):
        # The pager row is reserved in every page's pixel budget whether or not
        # it shows controls, so a zero-page state would have nothing to render.
        self.assertEqual(pager.page_count(0, 4), 1)

    def test_an_exact_fill_does_not_add_an_empty_page(self):
        self.assertEqual(pager.page_count(4, 4), 1)
        self.assertEqual(pager.page_count(8, 4), 2)

    def test_one_over_starts_a_new_page(self):
        self.assertEqual(pager.page_count(5, 4), 2)
        self.assertEqual(pager.page_count(9, 4), 3)

    def test_a_nonsense_page_size_does_not_divide_by_zero(self):
        self.assertEqual(pager.page_count(10, 0), 1)
        self.assertEqual(pager.page_count(10, -1), 1)


class ClampTests(unittest.TestCase):
    def test_a_valid_index_is_left_alone(self):
        # The whole point: a rebuild that changed nothing must not move the user.
        for index in range(3):
            self.assertEqual(pager.clamp_page(index, 12, 4), index)

    def test_a_rebuild_that_changed_nothing_holds_the_page(self):
        # Simulates the 3-second device poll firing while the user reads page 2:
        # same data, many rebuilds, same page every time.
        index = 2
        for _ in range(50):
            index = pager.clamp_page(index, 12, 4)
        self.assertEqual(index, 2)

    def test_a_list_that_grew_holds_the_page(self):
        self.assertEqual(pager.clamp_page(1, 8, 4), 1)
        self.assertEqual(pager.clamp_page(1, 40, 4), 1)

    def test_a_list_that_shrank_past_the_page_pulls_back_to_the_last(self):
        # The one case where holding still would show a blank page.
        self.assertEqual(pager.clamp_page(5, 8, 4), 1)

    def test_a_list_emptied_entirely_lands_on_page_zero(self):
        self.assertEqual(pager.clamp_page(5, 0, 4), 0)

    def test_a_negative_index_lands_on_page_zero(self):
        self.assertEqual(pager.clamp_page(-3, 12, 4), 0)


class PageItemsTests(unittest.TestCase):
    def setUp(self):
        self.items = list(range(10))

    def test_each_page_is_the_next_slice(self):
        self.assertEqual(pager.page_items(self.items, 0, 4), [0, 1, 2, 3])
        self.assertEqual(pager.page_items(self.items, 1, 4), [4, 5, 6, 7])
        self.assertEqual(pager.page_items(self.items, 2, 4), [8, 9])

    def test_no_page_ever_exceeds_the_capacity(self):
        # The invariant the whole design rests on: nothing is drawn past the
        # edge, for any list length and any page.
        for total in range(0, 40):
            items = list(range(total))
            for per_page in (1, 2, 3, 4, 7):
                for index in range(pager.page_count(total, per_page)):
                    shown = pager.page_items(items, index, per_page)
                    self.assertLessEqual(len(shown), per_page)

    def test_the_pages_together_are_the_whole_list_exactly_once(self):
        # Nothing lost, nothing shown twice -- the failure paging exists to fix.
        for total in range(0, 40):
            items = list(range(total))
            for per_page in (1, 2, 3, 4, 7):
                seen = []
                for index in range(pager.page_count(total, per_page)):
                    seen.extend(pager.page_items(items, index, per_page))
                self.assertEqual(seen, items)

    def test_an_out_of_range_page_is_clamped_not_blank(self):
        self.assertEqual(pager.page_items(self.items, 99, 4), [8, 9])


class LabelTests(unittest.TestCase):
    def test_it_reads_one_based(self):
        self.assertEqual(pager.label(0, 10, 4), "1 / 3")
        self.assertEqual(pager.label(2, 10, 4), "3 / 3")

    def test_an_empty_list_reads_as_one_of_one(self):
        self.assertEqual(pager.label(0, 0, 4), "1 / 1")

    def test_it_reports_the_clamped_page_not_the_asked_one(self):
        # The label must agree with what is actually drawn.
        self.assertEqual(pager.label(99, 10, 4), "3 / 3")


if __name__ == "__main__":
    unittest.main()
