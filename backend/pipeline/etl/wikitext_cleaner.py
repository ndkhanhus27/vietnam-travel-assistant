import html
import re
import unicodedata

import mwparserfromhell
from mwparserfromhell.nodes import Template
from mwparserfromhell.wikicode import Wikicode


# ================================================================
# TEMPLATE CONFIG
# ================================================================

# Template chứa dữ liệu du lịch thực tế.
LISTING_TEMPLATES = {
    "listing",
    "see",
    "do",
    "buy",
    "eat",
    "drink",
    "sleep",
    "go",
    "vicinity",
}


# Template chủ yếu phục vụ giao diện / navigation.
DROP_TEMPLATES = {
    "pagebanner",
    "banner",
    "geo",
    "mapframe",
    "maplink",
    "routebox",
    "quickbar",
    "otheruses",
    "disamb",
    "stub",
    "outlinecity",
    "usablecity",
    "guidecity",
    "starcity",
}


LISTING_TEXT_FIELDS = (
    "name",
    "alt",
    "address",
    "directions",
    "content",
    "description",
    "hours",
    "price",
    "phone",
    "email",
)


GENERIC_TEXT_FIELDS = (
    "name",
    "text",
    "content",
    "description",
    "1",
)


# ================================================================
# BASIC CLEANING
# ================================================================

def _normalize_template_name(
    name: str,
) -> str:
    return (
        name
        .strip()
        .replace("_", " ")
        .lower()
    )


def _normalize_unicode(
    text: str,
) -> str:
    return unicodedata.normalize(
        "NFC",
        text,
    )


def _remove_comments(
    text: str,
) -> str:
    return re.sub(
        r"<!--.*?-->",
        "",
        text,
        flags=re.DOTALL,
    )


def _remove_refs(
    text: str,
) -> str:
    # <ref>...</ref>
    text = re.sub(
        r"<ref\b[^>]*>.*?</ref>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # <ref ... />
    text = re.sub(
        r"<ref\b[^>]*/>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text


def _remove_html_tags(
    text: str,
) -> str:
    return re.sub(
        r"<[^>]+>",
        " ",
        text,
    )


# ================================================================
# MEDIAWIKI TABLE
# ================================================================

def _flatten_wiki_tables(
    text: str,
) -> str:
    """
    Không xóa nội dung table.

    Chuyển table MediaWiki thành text đơn giản.
    """

    lines = text.splitlines()

    output: list[str] = []

    inside_table = False

    for raw_line in lines:
        line = raw_line.strip()

        if line.startswith("{|"):
            inside_table = True
            continue

        if inside_table and line.startswith("|}"):
            inside_table = False
            continue

        if not inside_table:
            output.append(raw_line)
            continue

        if line.startswith("|-"):
            output.append("")
            continue

        if line.startswith("!"):
            value = line[1:].replace(
                "!!",
                " | ",
            )

            output.append(value)
            continue

        if line.startswith("|"):
            value = line[1:].replace(
                "||",
                " | ",
            )

            # Ví dụ:
            #
            # | style="..." | Nội dung
            if "|" in value:
                left, right = value.split(
                    "|",
                    maxsplit=1,
                )

                if (
                    "=" in left
                    and len(left) < 200
                ):
                    value = right

            output.append(value)

    return "\n".join(output)


# ================================================================
# TEMPLATE PROCESSING
# ================================================================

def _get_template_param(
    template: Template,
    name: str,
) -> str | None:
    for param in template.params:
        param_name = (
            str(param.name)
            .strip()
            .lower()
        )

        if param_name != name.lower():
            continue

        value = str(
            param.value
        ).strip()

        if value:
            return value

    return None


def _listing_template_to_text(
    template: Template,
) -> str:
    """
    Ví dụ:

    {{see
      |name=Biển Nhật Lệ
      |address=Đồng Hới
      |content=Bãi biển gần trung tâm.
    }}

    thành:

    Biển Nhật Lệ. Đồng Hới. Bãi biển gần trung tâm.
    """

    values: list[str] = []

    for field in LISTING_TEXT_FIELDS:
        value = _get_template_param(
            template,
            field,
        )

        if value:
            values.append(value)

    return ". ".join(values)


def _generic_template_to_text(
    template: Template,
) -> str:
    values: list[str] = []

    for field in GENERIC_TEXT_FIELDS:
        value = _get_template_param(
            template,
            field,
        )

        if value:
            values.append(value)

    return ". ".join(values)


def _process_templates(
    code: Wikicode,
) -> None:
    templates = list(
        code.filter_templates(
            recursive=True,
        )
    )

    # Template sâu xử lý trước.
    for template in reversed(
        templates
    ):
        name = _normalize_template_name(
            str(template.name)
        )

        if name in LISTING_TEMPLATES:
            replacement = (
                _listing_template_to_text(
                    template
                )
            )

        elif name in DROP_TEMPLATES:
            replacement = ""

        else:
            replacement = (
                _generic_template_to_text(
                    template
                )
            )

        try:
            code.replace(
                template,
                replacement,
            )
        except ValueError:
            continue


# ================================================================
# WIKILINK PROCESSING
# ================================================================

def _process_wikilinks(
    code: Wikicode,
) -> None:
    """
    [[Đồng Hới]]
        ->
    Đồng Hới

    [[Phong Nha-Kẻ Bàng|Phong Nha]]
        ->
    Phong Nha
    """

    links = list(
        code.filter_wikilinks(
            recursive=True,
        )
    )

    for link in links:
        if link.text is not None:
            replacement = str(
                link.text
            ).strip()
        else:
            replacement = str(
                link.title
            ).strip()

        try:
            code.replace(
                link,
                replacement,
            )
        except ValueError:
            continue


# ================================================================
# TEXT NORMALIZATION
# ================================================================

def _normalize_headings(
    text: str,
) -> str:
    """
    == Đi lại ==
        ->
    Đi lại
    """

    return re.sub(
        r"^\s*=+\s*(.*?)\s*=+\s*$",
        r"\1",
        text,
        flags=re.MULTILINE,
    )


def _normalize_list_markers(
    text: str,
) -> str:
    """
    * Nội dung
    # Nội dung
        ->
    Nội dung
    """

    return re.sub(
        r"^\s*[*#;:]+\s*",
        "",
        text,
        flags=re.MULTILINE,
    )


def _normalize_whitespace(
    text: str,
) -> str:
    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    text = text.replace(
        "\t",
        " ",
    )

    # Nhiều space -> 1.
    text = re.sub(
        r"[^\S\n]+",
        " ",
        text,
    )

    lines = [
        line.strip()
        for line in text.splitlines()
    ]

    text = "\n".join(
        lines
    )

    # Không cần quá 1 dòng trống.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


# ================================================================
# PUBLIC API
# ================================================================

def clean_wikitext(
    raw_wikitext: str,
) -> str:
    """
    Raw MediaWiki Wikitext -> plain text.

    Không sửa RawDocument.raw_content trong database.
    """

    if not raw_wikitext:
        return ""

    text = raw_wikitext

    text = _remove_comments(
        text
    )

    text = _remove_refs(
        text
    )

    text = _flatten_wiki_tables(
        text
    )

    code = mwparserfromhell.parse(
        text
    )

    _process_templates(
        code
    )

    _process_wikilinks(
        code
    )

    # Loại các markup MediaWiki còn lại.
    text = code.strip_code(
        normalize=True,
        collapse=False,
    )

    text = html.unescape(
        text
    )

    text = _remove_html_tags(
        text
    )

    text = _normalize_headings(
        text
    )

    text = _normalize_list_markers(
        text
    )

    text = _normalize_unicode(
        text
    )

    text = _normalize_whitespace(
        text
    )

    return text