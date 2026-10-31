"""Validate Boa login forms and recognize captured login/logout results."""

from html.parser import HTMLParser

from yarl import URL

from ...const import LOGIN_FORM_PATH, LOGIN_PAGE_PATH, LOGOUT_PAGE_PATH
from ...models import OnuAuthError, OnuLogoutError


class _LoginFormParser(HTMLParser):
    """Extract only the verified login form, ignoring language/settings forms."""

    def __init__(self, host: str) -> None:
        super().__init__(convert_charrefs=True)
        self._origin = URL(host)
        self.hidden: dict[str, str] = {}
        self.fields: set[str] = set()
        self.valid = False
        self._in_login_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            try:
                target = self._origin.join(URL(attributes.get("action") or ""))
                self._in_login_form = (
                    target.origin() == self._origin
                    and target.path == LOGIN_FORM_PATH
                    and target.user is None
                    and target.password is None
                    and not target.query_string
                    and not target.fragment
                    and (attributes.get("method") or "get").lower() == "post"
                )
            except ValueError:
                self._in_login_form = False
        elif tag == "input" and self._in_login_form and (name := attributes.get("name")):
            self.fields.add(name)
            if (attributes.get("type") or "text").lower() == "hidden":
                self.hidden[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._in_login_form:
            self.valid = {"username", "password", "save"} <= self.fields
            self._in_login_form = False


class _FormResultParser(HTMLParser):
    """Read visible form results without trusting comments or scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[str] = []
        self._heading: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored += 1
        if not self._ignored and tag == "h4":
            self._heading = []

    def handle_data(self, data: str) -> None:
        if self._heading is not None and not self._ignored:
            self._heading.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        if not self._ignored and tag == "h4" and self._heading is not None:
            message = " ".join("".join(self._heading).split()).casefold()
            self.messages.append(message)
            self._heading = None

    @property
    def logout_success(self) -> bool:
        return "ok: logout successfully!" in self.messages

    @property
    def session_busy(self) -> bool:
        return "error: you have logined! please logout at first and then login!" in self.messages


def login_payload(html: str, host: str, username: str, password: str) -> dict[str, str]:
    """Build only the verified same-origin form POST, preserving hidden fields."""
    parser = _LoginFormParser(host)
    parser.feed(html)
    parser.close()
    if not parser.valid or parser.hidden.get("challenge"):
        raise OnuAuthError("The device returned an unsupported login form")
    return {
        **parser.hidden,
        "challenge": "",
        "username": username,
        "password": password,
        "save": "Login",
        "submit-url": LOGIN_PAGE_PATH,
    }


def login_result(html: str) -> tuple[bool, bool]:
    """Return session ownership and a busy response without trusting page scripts."""
    parser = _FormResultParser()
    parser.feed(html)
    parser.close()
    return (
        not any(message.startswith("error:") for message in parser.messages),
        parser.session_busy,
    )


def logout_payload() -> dict[str, str]:
    """Reproduce the captured logout action, without visiting the logout page."""
    return {"save": "Logout", "submit-url": LOGOUT_PAGE_PATH}


def validate_logout(html: str) -> None:
    """Require the explicit acknowledgement rather than accepting HTTP 200 alone."""
    parser = _FormResultParser()
    parser.feed(html)
    parser.close()
    if not parser.logout_success:
        raise OnuLogoutError("The device did not confirm successful logout")
