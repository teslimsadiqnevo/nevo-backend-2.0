"""One look for every email Nevo sends.

Every message went out as plain text: correct, delivered, and indistinguishable
from a script. A school being asked to click a consent link, or a parent given
a sign-in code, has no way to tell a real Nevo email from anything else that
knows their address, and that matters most on exactly the messages that ask
somebody to click something.

The layout is a nest of tables with inline styles on purpose. Mail clients strip
stylesheets, several ignore flexbox entirely, and Outlook renders through Word -
so the things that would be obvious in a browser are the things that break here.

The plain-text part is never dropped. It is what a screen reader, a watch, and a
client with images turned off actually render, so every message still has to
stand up without any of this.
"""

from __future__ import annotations

from html import escape

#: Nevo's own palette, taken from the landing page rather than invented.
INK = "#2b2b2f"
INDIGO = "#3b3f6e"
CREAM = "#f7f1e6"
PAPER = "#ffffff"
MUTED = "#6b6b73"
RULE = "#ded7c8"

#: Absolute, and on the apex the assets actually resolve to. nevolearning.com
#: 307s to www, and a mail client that will not follow a redirect for an image
#: shows a broken one instead - which looks worse than no logo at all.
LOGO_URL = "https://www.nevolearning.com/brand/nevo-wordmark.png"
LOGO_WIDTH = 116
LOGO_HEIGHT = 39

SUPPORT_EMAIL = "support@nevolearning.com"

FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


def _paragraph(text: str) -> str:
    return (
        f'<p style="margin:0 0 16px;font-family:{FONT_STACK};font-size:16px;'
        f'line-height:1.6;color:{INK}">{text}</p>'
    )


def _button(label: str, url: str) -> str:
    """A link that looks like a button without relying on CSS.

    Rendered as a single-cell table because a padded anchor collapses in
    Outlook, which is the client a Nigerian school office is most likely to be
    reading this in.
    """

    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px 0 24px">'
        f'<tr><td align="center" bgcolor="{INDIGO}" style="border-radius:6px">'
        f'<a href="{escape(url, quote=True)}" '
        f'style="display:inline-block;padding:13px 28px;font-family:{FONT_STACK};'
        f"font-size:16px;font-weight:600;color:#ffffff;text-decoration:none;"
        f'border-radius:6px">{escape(label)}</a>'
        "</td></tr></table>"
    )


def render_email(
    *,
    heading: str,
    paragraphs: list[str],
    cta: tuple[str, str] | None = None,
    footnote: str | None = None,
    preheader: str | None = None,
) -> str:
    """Wrap a message in Nevo's shell.

    ``paragraphs`` and ``heading`` are escaped, because several callers pass a
    school name, a lesson title or a teacher's own words straight through.
    ``cta`` is a (label, url) pair rendered as a button; a link in the text is
    still the fallback for anybody the button does not reach.
    ``preheader`` is the grey line an inbox shows beside the subject - left
    unset it shows the first thing in the body, which is usually the logo's
    alt text.
    """

    body = "".join(_paragraph(escape(item)) for item in paragraphs)
    if cta is not None:
        body += _button(*cta)
    if footnote:
        body += (
            f'<p style="margin:24px 0 0;font-family:{FONT_STACK};font-size:13px;'
            f'line-height:1.5;color:{MUTED}">{escape(footnote)}</p>'
        )

    hidden = ""
    if preheader:
        hidden = (
            '<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
            f"{escape(preheader)}</div>"
        )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{escape(heading)}</title>
</head>
<body style="margin:0;padding:0;background:{CREAM}">
{hidden}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:{CREAM};padding:32px 12px">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
           style="width:100%;max-width:600px">
      <tr><td style="padding:0 4px 20px">
        <img src="{LOGO_URL}" width="{LOGO_WIDTH}" height="{LOGO_HEIGHT}" alt="Nevo"
             style="display:block;border:0;outline:none;text-decoration:none">
      </td></tr>
      <tr><td style="background:{PAPER};border:1px solid {RULE};border-radius:10px;
                     padding:32px 28px">
        <h1 style="margin:0 0 18px;font-family:{FONT_STACK};font-size:22px;
                   line-height:1.3;font-weight:700;color:{INK}">{escape(heading)}</h1>
        {body}
      </td></tr>
      <tr><td style="padding:22px 4px 0">
        <p style="margin:0 0 6px;font-family:{FONT_STACK};font-size:13px;
                  line-height:1.5;color:{MUTED}">
          Nevo &middot; learning that adapts to the child
        </p>
        <p style="margin:0;font-family:{FONT_STACK};font-size:13px;
                  line-height:1.5;color:{MUTED}">
          Need help? <a href="mailto:{SUPPORT_EMAIL}"
             style="color:{INDIGO};text-decoration:underline">{SUPPORT_EMAIL}</a>
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""
