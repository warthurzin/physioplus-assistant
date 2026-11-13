from typing import Protocol, Sequence

import numpy as np


class TextEncoder(Protocol):
    model_name: str
    max_seq_length: int

    def encode(self, texts: Sequence[str], show_progress: bool = False) -> np.ndarray: ...

    def count_tokens(self, texts: Sequence[str]) -> list[int]: ...


class Embedder:
    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)

        return self._model

    @property
    def max_seq_length(self) -> int:
        return int(self._get_model().max_seq_length)

    def encode(self, texts: Sequence[str], show_progress: bool = False) -> np.ndarray:
        vectors = self._get_model().encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
        )
        return np.asarray(vectors, dtype="float32")

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        tokenizer = self._get_model().tokenizer
        encoded = tokenizer(list(texts), add_special_tokens=True)
        return [len(ids) for ids in encoded["input_ids"]]
