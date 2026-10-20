import json
import math
import re
from pathlib import Path
from typing import List, Dict, Any
from backend.config import DATA_DIR

MEMORY_FILE = DATA_DIR / "agent_memory.json"


def tokenize(text: str) -> List[str]:
    return re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", text.lower())


class SimpleVectorMemory:
    """
    Lightweight, embedded semantic memory store.
    Stores key learnings, facts, and past task summaries.
    Uses TF-IDF vector similarity with zero heavy C++ dependency hassles,
    persisting cleanly to data/agent_memory.json.
    """

    def __init__(self, storage_path: Path = MEMORY_FILE):
        self.storage_path = Path(storage_path)
        self.documents: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if self.storage_path.exists():
            try:
                self.documents = json.loads(self.storage_path.read_text(encoding="utf-8"))
            except Exception:
                self.documents = []
        else:
            self.documents = []

    def _save(self):
        self.storage_path.write_text(json.dumps(self.documents, indent=2), encoding="utf-8")

    def add(self, text: str, metadata: Dict[str, Any] = None) -> None:
        if not text or not text.strip():
            return
        doc = {
            "text": text.strip(),
            "metadata": metadata or {},
            "tokens": tokenize(text)
        }
        self.documents.append(doc)
        self._save()

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.documents:
            return []

        # Simple BM25 / TF-IDF scoring
        scores = []
        doc_count = len(self.documents)
        
        # Calculate document frequency
        df = {}
        for token in query_tokens:
            df[token] = sum(1 for d in self.documents if token in d["tokens"])

        for doc in self.documents:
            score = 0.0
            doc_len = max(len(doc["tokens"]), 1)
            for token in query_tokens:
                if token in doc["tokens"]:
                    tf = doc["tokens"].count(token) / doc_len
                    idf = math.log((doc_count + 1) / (df[token] + 1)) + 1
                    score += tf * idf
            if score > 0:
                scores.append((score, doc))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [{"text": doc["text"], "metadata": doc["metadata"], "score": s} for s, doc in scores[:limit]]


memory = SimpleVectorMemory()
