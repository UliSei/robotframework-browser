__version__ = "0.1.0"

import os
from subprocess import Popen, STDOUT
import contextlib
from functools import cached_property
import time
from typing import Optional

import grpc  # type: ignore

from robot.api import logger  # type: ignore
from robot.libraries.BuiltIn import BuiltIn  # type: ignore

import Playwright.generated.playwright_pb2 as playwright_pb2
from Playwright.generated.playwright_pb2 import Empty
import Playwright.generated.playwright_pb2_grpc as playwright_pb2_grpc

from .util import find_free_port

_SUPPORTED_BROWSERS = ["chrome", "firefox", "webkit"]


class Playwright:
    """Playwright library is a web testing library for Robot Framework.

    This documents explains how to use keywords provided by the Playwright
    library. For information about installation, support, and more, please
    visit the
    [https://github.com/MarketSquare/robotframework-playwright|project pages].
    For more information about Robot Framework, see http://robotframework.org.

    Playwright library uses
    [https://github.com/microsoft/playwright|Playwright Node module]
    to automate [https://www.chromium.org/Home|Chromium],
    [https://www.mozilla.org/en-US/firefox/new/|Firefox]
    and [https://webkit.org/|WebKit] with a single library.

    == Table of contents ==

    %TOC%

    = Locating elements =

    All keywords in Playwright library that need to interact with an element
    on a web page take an argument typically named ``locator`` that specifies
    how to find the element.

    == Locator syntax ==

    Playwright library supports same locator strategies as the underlying
    Playwright None module: xpath, css, id and text. The strategy can either
    be explicitly specified with a prefix or the strategy can be implicit.

    === Implicit locator strategy ===

    The default locator strategy is `css`. If locator does not contain
    one of the know locator strategies, `css`, `xpath`, `id` or `text` it is
    assumed to contain css locator. Also `locators` starting with `//` is
    considered as xpath locators.

    Examples:

    | `Click` | span > button | # Use css locator strategy the element.   |
    | `Click` | //span/button | # Use xpath locator strategy the element. |

    === Explicit locator strategy ===

    The explicit locator strategy is specified with a prefix using syntax
    ``strategy:value``. Spaces around the separator are ignored, so
    ``css:foo``, ``css: foo`` and ``css : foo`` are all equivalent.

    Locator strategies that are supported by default are listed in the table
    below.

    | = Strategy = |     = Match based on =     |         = Example =            |
    | css          | CSS selector.              | ``css:div#example``            |
    | xpath        | XPath expression.          | ``xpath://div[@id="example"]`` |
    | text         | Playwright text engine.    | ``text:Login``                 |
    | id           | Converted to CSS selector. | ``id:example``                 |
    """

    ROBOT_LISTENER_API_VERSION = 2
    ROBOT_LIBRARY_LISTENER: "Playwright"
    ROBOT_LIBRARY_SCOPE = "GLOBAL"
    port: Optional[str] = None

    def __init__(self):
        self.ROBOT_LIBRARY_LISTENER = self
        self.ROBOT_OUTPUT_DIR = BuiltIn().get_variable_value("${OUTPUTDIR}")

    @cached_property
    def _playwright_process(self) -> Popen:
        cwd_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wrapper")
        path_to_script = os.path.join(cwd_dir, "index.js")
        logger.info(f"Starting Playwright process {path_to_script}")
        logfile = open(os.path.join(self.ROBOT_OUTPUT_DIR, "playwright-log.txt"), "w")
        self.port = str(find_free_port())
        popen = Popen(
            ["node", path_to_script],
            shell=False,
            cwd=cwd_dir,
            env={"PORT": self.port, "PATH": os.environ["PATH"]},
            stdout=logfile,
            stderr=STDOUT,
        )
        for i in range(50):
            with grpc.insecure_channel(f"localhost:{self.port}") as channel:
                try:
                    stub = playwright_pb2_grpc.PlaywrightStub(channel)
                    response = stub.Health(Empty())
                    logger.info(
                        f"Connected to the playwright process at port ${self.port}: ${response}"
                    )
                    return popen
                except grpc.RpcError:
                    time.sleep(0.1)
        raise RuntimeError(
            f"Could not connect to the playwright process at port ${self.port}"
        )

    def _close(self):
        logger.debug("Closing Playwright process")
        self._playwright_process.kill()
        logger.debug("Playwright process killed")

    # Yields a PlayWrightstub on a newly initialized channel and
    # closes channel after control returns
    @contextlib.contextmanager
    def insecure_stub(self):
        if self._playwright_process.poll() is not None:
            raise ConnectionError("Playwright process has been terminated")
        channel = grpc.insecure_channel(f"localhost:{self.port}")
        yield playwright_pb2_grpc.PlaywrightStub(channel)
        channel.close()

    # Control keywords
    def open_browser(self, browser="Chrome", url=None):
        browser_ = browser.lower().strip()
        if browser_ not in _SUPPORTED_BROWSERS:
            raise ValueError(
                f"{browser} is not supported, "
                f'it should be one of: {", ".join(_SUPPORTED_BROWSERS)}'
            )
        with self.insecure_stub() as stub:
            response = stub.OpenBrowser(
                playwright_pb2.openBrowserRequest(url=url or "", browser=browser_)
            )
            logger.info(response.log)

    def close_browser(self):
        with self.insecure_stub() as stub:
            response = stub.CloseBrowser(Empty())
            logger.info(response.log)

    def go_to(self, url: str):
        with self.insecure_stub() as stub:
            response = stub.GoTo(playwright_pb2.goToRequest(url=url))
            logger.info(response.log)

    # Input keywords
    def input_text(self, selector: str, text: str):
        with self.insecure_stub() as stub:
            response = stub.InputText(
                playwright_pb2.inputTextRequest(input=text, selector=selector)
            )
            logger.info(response.log)

    def click_button(self, selector: str):
        with self.insecure_stub() as stub:
            response = stub.ClickButton(
                playwright_pb2.selectorRequest(selector=selector)
            )
            logger.info(response.log)

    # Validation keywords
    def location_should_be(self, url: str):
        with self.insecure_stub() as stub:
            page_url = stub.GetUrl(Empty()).body
            if url != page_url:
                raise AssertionError(
                    "URL should be `{}`  but was `{}`".format(url, page_url)
                )

    def textfield_value_should_be(self, selector: str, text: str):
        with self.insecure_stub() as stub:
            response = stub.GetInputValue(
                playwright_pb2.selectorRequest(selector=selector)
            )
            logger.info(response.log)
            if response.body != text:
                raise AssertionError(
                    "Textfield {} content should be {} but was `{}`".format(
                        selector, text, response.body
                    )
                )

    def title_should_be(self, title: str):
        with self.insecure_stub() as stub:
            response = stub.GetTitle(Empty())
            logger.info(response.log)
            if response.body != title:
                raise AssertionError(
                    "Title should be {} but was `{}`".format(title, response.body)
                )

    def page_should_contain(self, text: str):
        with self.insecure_stub() as stub:
            response = stub.GetTextContent(
                playwright_pb2.selectorRequest(selector="text=" + text)
            )
            logger.info(response.log)
            if response.body != text:
                raise AssertionError("No element with text `{}` on page".format(text))
