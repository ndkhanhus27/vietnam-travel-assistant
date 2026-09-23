def split_for_entity_extraction(
    content: str,
    *,
    max_chars: int,
) -> list[str]:
    """
    Chia document thành extraction windows tạm.

    KHÔNG:
    - lưu DB
    - tạo retrieval chunks
    - liên quan chunk_size=512

    Chỉ dùng để tránh request AI quá dài.
    """

    content = content.strip()

    if not content:
        return [""]

    if len(content) <= max_chars:
        return [content]

    paragraphs = [
        paragraph.strip()
        for paragraph
        in content.split("\n\n")
        if paragraph.strip()
    ]

    windows: list[str] = []

    current: list[str] = []
    current_length = 0

    for paragraph in paragraphs:

        # --------------------------------------------------------
        # PARAGRAPH QUÁ DÀI
        # --------------------------------------------------------

        if len(paragraph) > max_chars:

            if current:
                windows.append(
                    "\n\n".join(current)
                )

                current = []
                current_length = 0

            start = 0

            while start < len(paragraph):
                end = (
                    start
                    + max_chars
                )

                windows.append(
                    paragraph[
                        start:end
                    ]
                )

                start = end

            continue

        # --------------------------------------------------------
        # NORMAL PARAGRAPH
        # --------------------------------------------------------

        separator_size = (
            2
            if current
            else 0
        )

        projected_length = (
            current_length
            + separator_size
            + len(paragraph)
        )

        if (
            current
            and projected_length
            > max_chars
        ):
            windows.append(
                "\n\n".join(current)
            )

            # Semantic overlap:
            # giữ paragraph cuối của window trước.
            previous = (
                current[-1]
            )

            current = [
                previous
            ]

            current_length = len(
                previous
            )

        if current:
            current_length += 2

        current.append(
            paragraph
        )

        current_length += len(
            paragraph
        )

    if current:
        final_window = (
            "\n\n".join(
                current
            )
        )

        if (
            not windows
            or final_window
            != windows[-1]
        ):
            windows.append(
                final_window
            )

    return windows