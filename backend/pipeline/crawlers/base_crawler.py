from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceConfig:
    name: str
    api_url: str
    wiki_base_url: str
    license: str
    language: str
    # Các category gốc đã xác minh. Crawler duyệt toàn bộ cây con theo BFS.
    category_titles: tuple[str, ...]
    max_category_depth: int = 8


APPROVED_SOURCES = {
    "wikivoyage_vi": SourceConfig(
        name="Wikivoyage tiếng Việt",
        api_url="https://vi.wikivoyage.org/w/api.php",
        wiki_base_url="https://vi.wikivoyage.org",
        license="CC BY-SA 4.0",
        language="vi",
        # Một root là đủ vì crawler đi BFS hết các category con: điểm đến
        # Bắc, Trung, Nam. Chỉ thêm seed mới sau khi kiểm tra nó tồn tại.
        category_titles = (
            "Thể loại:Việt Nam",              
        ),
        max_category_depth=8,
    ),
    # Thêm Wikidata và UNESCO ở bước kế tiếp.
}


@dataclass(frozen=True)
class CrawledRawDocument:
    title: str
    source_name: str
    source_url: str
    license: str
    language: str
    raw_content: str
    content_format: str
    revision_id: str | None
    fetched_at: datetime


class BaseCrawler(ABC):
    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    @abstractmethod
    async def crawl(self, limit: int) -> list[CrawledRawDocument]:
        """Trả về raw documents, không transform ``raw_content``."""
        raise NotImplementedError
