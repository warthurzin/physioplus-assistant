from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    title: str
    category: str
    section: str
    text: str
    version: str
    source: str

    @property
    def embedding_text(self) -> str:
        return f"{self.title}. {self.section}. {self.text}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        return cls(**data)
