# Paged lists -- how a list that outgrows the glass stays reachable.
#
# The RGB panel bans scrolling: w_group removes SCROLLABLE from every container
# (widgets.py:30) and shell does the same to every sub-page body (shell.py:63).
# So an item that does not fit is drawn past the edge and lost in silence --
# LVGL clips the pixels and nothing complains. Three screens grow with use:
# rooms, the devices in one room, and schedules. A lost item there is not
# cosmetic; it is a schedule you cannot delete and a light you cannot switch
# off, both of which exist in storage and fire on time.
#
# Why paging, and not the two alternatives:
#
#   * A card that shrinks with the list buys one doubling, breaks anyway, and
#     drags the tap target under theme.TAP_MIN on the way. It turns a sharp
#     failure into a graded one, which is worse -- it arrives without warning.
#   * A declared ceiling ("showing 4 of 7") makes the item visible but
#     unreachable. For three lists the user must *edit*, that is no better than
#     invisible.
#
# Paging is bounded by construction, grows to any list, and leaves the tap
# target alone. It is also the motion this panel already does well: a static
# swap with no animation, which is all the RGB scanout can feed.
#
# One module because the concept crosses three files that do not import each
# other, and CLAUDE.md answers that with a single source rather than three
# copies. Pure Python, no LVGL -- the arithmetic is unit-tested on CPython
# (tests/test_panel_pager.py), and only the pixel capacity needs the board.


def page_count(total, per_page):
    """Pages needed to show ``total`` items, never fewer than one.

    An empty list is still one page. Every page reserves the pager row in its
    pixel budget whether or not it has controls to show, so "no pages at all"
    is not a state the layout has to render.
    """
    if per_page < 1 or total < 1:
        return 1
    return (total + per_page - 1) // per_page


def clamp_page(index, total, per_page):
    """Hold a page index inside the list as the list changes underneath it.

    This is the part a naive pager gets wrong. _rebuild runs on every store
    write, and on product A the device poll writes every three seconds
    (main.py:_devices_refresh), so a user reading page 2 has the list rebuilt
    under them constantly. Snapping back to page 0 there would throw them to
    the top mid-action, over and over, for a refresh that changed nothing.

    The index therefore moves only when the list actually shrank past it --
    the one case where holding still would show a blank page.
    """
    if index < 1:
        return 0
    last = page_count(total, per_page) - 1
    return last if index > last else index


def page_items(items, index, per_page):
    """The slice of ``items`` visible on page ``index``, clamped."""
    if per_page < 1:
        return items
    start = clamp_page(index, len(items), per_page) * per_page
    return items[start:start + per_page]


def label(index, total, per_page):
    """The position readout, e.g. "2 / 3". One-based, for humans."""
    return "{} / {}".format(clamp_page(index, total, per_page) + 1,
                            page_count(total, per_page))
