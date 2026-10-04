import asyncio
import re
import sqlite3
from typing import ClassVar

from nicegui import app, ui

from db import (
    add_bookmark,
    add_feed,
    get_bookmarked_urls,
    get_feeds,
    init_db,
    remove_bookmark,
    remove_feed,
    update_feed,
)
from rss import Article, fetch_all_feeds

REFRESH_INTERVAL = 15 * 60  # seconds

init_db()


# ── State ──────────────────────────────────────────────────────────────────────

class State:
    articles: ClassVar[list[Article]] = []
    bookmarks: set[str] = get_bookmarked_urls()
    active_category: str = "All"
    search_query: str = ""
    loading: bool = False

    @property
    def categories(self) -> list[str]:
        cats = sorted({a.category for a in self.articles})
        return ["All", "Bookmarks"] + cats

    def filtered(self) -> list[Article]:
        results = self.articles
        if self.active_category == "Bookmarks":
            results = [a for a in results if a.url in self.bookmarks]
        elif self.active_category != "All":
            results = [a for a in results if a.category == self.active_category]
        if self.search_query:
            q = self.search_query.lower()
            results = [
                a for a in results
                if q in a.title.lower() or q in a.summary.lower() or q in a.source.lower()
            ]
        return results


state = State()

_URL_RE = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)


def render_summary(text: str):
    parts = _URL_RE.split(text)
    with ui.row().classes("text-sm text-gray-600 mt-1 leading-relaxed flex-wrap gap-0 items-baseline"):
        for i, part in enumerate(parts):
            if not part:
                continue
            if i % 2 == 1:
                ui.link(part, part, new_tab=True).classes("text-blue-600 hover:underline break-all")
            else:
                ui.label(part)


# ── Background refresh ─────────────────────────────────────────────────────────

async def background_refresh():
    """Periodically re-fetch all feeds and update shared state."""
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        state.articles = await fetch_all_feeds(get_feeds())


@app.on_startup
async def start_background_refresh():
    asyncio.ensure_future(background_refresh())


# ── UI helpers ─────────────────────────────────────────────────────────────────

def article_card(article: Article, refresh_fn):
    is_bookmarked = article.url in state.bookmarks

    with (
        ui.card().classes("w-full p-4 hover:shadow-md transition-shadow cursor-pointer"),
        ui.row().classes("w-full items-start justify-between gap-2"),
    ):
        with ui.column().classes("flex-1 gap-1"):
            ui.link(article.title, article.url, new_tab=True).classes(
                "text-base font-semibold text-blue-700 hover:underline leading-snug"
            )
            with ui.row().classes("items-center gap-2 text-xs text-gray-500"):
                ui.badge(article.category, color="indigo").classes("text-xs")
                ui.label(article.source).classes("font-medium")
                if article.published_str:
                    ui.label("·")
                    ui.label(article.published_str)
            if article.summary:
                render_summary(article.summary)

        def toggle_bookmark(a=article):
            if a.url in state.bookmarks:
                state.bookmarks.discard(a.url)
                remove_bookmark(a.url)
            else:
                state.bookmarks.add(a.url)
                add_bookmark(a)
            refresh_fn()

        bookmark_icon = "bookmark" if is_bookmarked else "bookmark_border"
        bookmark_color = "text-yellow-500" if is_bookmarked else "text-gray-400"
        ui.button(icon=bookmark_icon, on_click=toggle_bookmark).props("flat round").classes(
            f"{bookmark_color} hover:text-yellow-500"
        )


def render_articles(container, articles: list[Article], refresh_fn):
    container.clear()
    with container:
        if state.loading:
            with ui.column().classes("w-full items-center py-16 gap-3"):
                ui.spinner(size="lg")
                ui.label("Fetching latest news…").classes("text-gray-500")
        elif not articles:
            with ui.column().classes("w-full items-center py-16"):
                ui.icon("newspaper", size="3rem").classes("text-gray-300")
                ui.label("No articles found").classes("text-gray-400 mt-2")
        else:
            for article in articles:
                article_card(article, refresh_fn)


SHARED_STYLES = """
<style>
    .body--light { background: #f8fafc; }
    .body--dark  { background: #121212; }
    .body--light .q-header { background: white;   box-shadow: 0 1px 3px rgba(0,0,0,.08); }
    .body--dark  .q-header { background: #1e1e2e; box-shadow: 0 1px 3px rgba(0,0,0,.4);  }
    .body--light .q-card   { border: 1px solid #e2e8f0; border-radius: 12px !important; }
    .body--dark  .q-card   { border: 1px solid #2d2d3d; border-radius: 12px !important; }
</style>
"""


# ── Main page ──────────────────────────────────────────────────────────────────

@ui.page("/")
async def index():
    ui.add_head_html(SHARED_STYLES)
    dark = ui.dark_mode()

    # ── Header ──
    with ui.header().classes("px-6 py-3 flex items-center gap-4"):
        ui.icon("newspaper", size="2rem").classes("text-indigo-600")
        ui.label("RSS Reader").classes("text-xl font-bold mr-4")

        search = ui.input(placeholder="Search articles…").classes("flex-1 max-w-md").props(
            "outlined dense clearable"
        )

        refresh_btn = ui.button("Refresh", icon="refresh").props("flat").classes("text-indigo-600")
        ui.button("Manage Feeds", icon="settings").props("flat").on(
            "click", lambda: ui.navigate.to("/feeds")
        )
        ui.button(icon="dark_mode").props("flat round").on(
            "click", dark.toggle
        )

    # ── Body ──
    with ui.row().classes("w-full max-w-6xl mx-auto px-4 py-6 gap-6 items-start"):

        # Sidebar – categories
        with ui.card().classes("w-48 p-2 sticky top-4"):
            ui.label("Categories").classes("text-xs font-semibold text-gray-400 uppercase px-2 py-1")
            cat_container = ui.column().classes("w-full gap-0")

        # Article list
        article_container = ui.column().classes("flex-1 gap-3")

    # ── Reactive helpers ───────────────────────────────────────────────────────

    def refresh_ui():
        articles = state.filtered()
        render_articles(article_container, articles, refresh_ui)

        # rebuild category sidebar
        cat_container.clear()
        with cat_container:
            for cat in state.categories:
                is_active = cat == state.active_category
                btn = ui.button(
                    f"{cat} ({sum(1 for a in state.articles if cat == 'All' or (cat == 'Bookmarks' and a.url in state.bookmarks) or a.category == cat)})",
                ).classes(
                    "w-full text-left rounded-lg px-3 py-1.5 text-sm " +
                    ("bg-indigo-600 text-white" if is_active else "text-gray-700 hover:bg-gray-100")
                ).props("flat align=left")

                def make_handler(c=cat):
                    def handler():
                        state.active_category = c
                        refresh_ui()
                    return handler

                btn.on("click", make_handler())

    async def load_feeds():
        state.loading = True
        refresh_ui()
        try:
            state.articles = await fetch_all_feeds(get_feeds())
        finally:
            state.loading = False
            refresh_ui()

    def on_search(e):
        state.search_query = e.value or ""
        refresh_ui()

    search.on_value_change(on_search)
    refresh_btn.on("click", lambda: asyncio.ensure_future(load_feeds()))

    # initial load — schedule as background task so the page response is not held up
    asyncio.ensure_future(load_feeds())


# ── Feeds management page ───────────────────────────────────────────────────────

@ui.page("/feeds")
def feeds_page():
    ui.add_head_html(SHARED_STYLES)
    dark = ui.dark_mode()

    with ui.header().classes("px-6 py-3 flex items-center gap-4"):
        ui.button(icon="arrow_back").props("flat round").on(
            "click", lambda: ui.navigate.to("/")
        )
        ui.icon("settings", size="2rem").classes("text-indigo-600")
        ui.label("Manage Feeds").classes("text-xl font-bold")
        ui.space()
        ui.button(icon="dark_mode").props("flat round").on(
            "click", dark.toggle
        )

    with ui.column().classes("w-full max-w-3xl mx-auto px-4 py-6 gap-4"):

        # ── Feed list ──
        feed_list = ui.column().classes("w-full gap-2")

        def render_feeds():
            feed_list.clear()
            with feed_list:
                for feed in get_feeds():
                    with (
                        ui.card().classes("w-full p-3"),
                        ui.row().classes("w-full items-center gap-3"),
                    ):
                        with ui.column().classes("flex-1 gap-0"):
                            ui.label(feed["name"]).classes("font-semibold text-gray-800")
                            ui.label(feed["url"]).classes("text-xs text-gray-400 break-all")
                            ui.badge(feed["category"], color="indigo").classes("text-xs w-fit mt-1")

                        ui.button(icon="edit").props("flat round").classes("text-gray-400").on(
                            "click", lambda f=feed: open_edit_dialog(f)
                        )
                        ui.button(icon="delete").props("flat round").classes("text-red-400").on(
                            "click", lambda f=feed: confirm_delete(f)
                        )

        def confirm_delete(feed: dict):
            with ui.dialog() as dlg, ui.card().classes("p-6 gap-4 min-w-72"):
                ui.label(f'Remove "{feed["name"]}"?').classes("font-semibold text-gray-800")
                ui.label("This will delete the feed. Articles already loaded won't be affected until next refresh.").classes("text-sm text-gray-500")
                with ui.row().classes("justify-end gap-2 w-full"):
                    ui.button("Cancel", on_click=dlg.close).props("flat")
                    def do_delete(f=feed):
                        remove_feed(f["url"])
                        dlg.close()
                        render_feeds()
                    ui.button("Remove", on_click=do_delete).classes("bg-red-500 text-white")
            dlg.open()

        def open_edit_dialog(feed: dict):
            with ui.dialog() as dlg, ui.card().classes("p-6 gap-4 min-w-96"):
                ui.label("Edit Feed").classes("font-semibold text-gray-800 text-lg")
                name_input = ui.input("Name", value=feed["name"]).classes("w-full").props("outlined dense")
                url_input = ui.input("URL", value=feed["url"]).classes("w-full").props("outlined dense")
                cat_input = ui.input("Category", value=feed["category"]).classes("w-full").props("outlined dense")
                with ui.row().classes("justify-end gap-2 w-full"):
                    ui.button("Cancel", on_click=dlg.close).props("flat")
                    def do_save(f=feed):
                        name = name_input.value.strip()
                        url = url_input.value.strip()
                        cat = cat_input.value.strip()
                        if not (name and url and cat):
                            ui.notify("All fields are required.", type="warning")
                            return
                        update_feed(f["url"], name, url, cat)
                        dlg.close()
                        render_feeds()
                    ui.button("Save", on_click=do_save).classes("bg-indigo-600 text-white")
            dlg.open()

        # ── Add feed form ──
        with ui.card().classes("w-full p-4"):
            ui.label("Add Feed").classes("font-semibold text-gray-700 mb-2")
            with ui.row().classes("w-full gap-2 items-end flex-wrap"):
                name_input = ui.input("Name").classes("flex-1 min-w-32").props("outlined dense")
                url_input = ui.input("URL").classes("flex-2 min-w-64").props("outlined dense")
                cat_input = ui.input("Category").classes("flex-1 min-w-32").props("outlined dense")
                def do_add():
                    name = name_input.value.strip()
                    url = url_input.value.strip()
                    cat = cat_input.value.strip()
                    if not (name and url and cat):
                        ui.notify("All fields are required.", type="warning")
                        return
                    try:
                        add_feed(name, url, cat)
                        name_input.set_value("")
                        url_input.set_value("")
                        cat_input.set_value("")
                        render_feeds()
                    except sqlite3.IntegrityError:
                        ui.notify("A feed with that URL already exists.", type="negative")
                ui.button("Add", icon="add", on_click=do_add).classes("bg-indigo-600 text-white")

        render_feeds()


ui.run(title="RSS Reader", port=8080, reload=False)
