"""Boolean parser an toàn và ranking BM25/TF-IDF cho OCR/ASR Unicode.

Grammar: OR có precedence thấp hơn AND; NOT một ngôi; parentheses và phrase
trong dấu ngoặc kép. Các term liên tiếp ngầm AND. Không dùng eval/SQL query.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict


def tokenize(text: str) -> list[str]:
    """NFC + casefold, giữ dấu tiếng Việt; chưa stemming hoặc tách từ ghép."""
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).casefold(), flags=re.UNICODE)


def normalize_text(text: str) -> str:
    """Chuẩn hóa thống nhất ingest/query mà vẫn lưu text gốc để hiển thị."""
    return " ".join(tokenize(text))


class BooleanParser:
    """Recursive descent; cây tuple với leaf là term hoặc phrase token."""
    def __init__(self, query: str):
        if len(query) > 4096:
            raise ValueError("Boolean query quá dài.")
        self.tokens: list[tuple[str, object]] = []
        position = 0
        while position < len(query):
            if query[position].isspace():
                position += 1
                continue
            character = query[position]
            if character in "()":
                self.tokens.append((character, character))
                position += 1
            elif character == '"':
                end = query.find('"', position + 1)
                if end < 0:
                    raise ValueError("Phrase thiếu dấu ngoặc kép đóng.")
                words = tokenize(query[position + 1:end])
                if not words:
                    raise ValueError("Phrase phải có ít nhất một term.")
                self.tokens.append(("leaf", tuple(words)))
                position = end + 1
            else:
                match = re.match(r'[^\s()"]+', query[position:])
                if not match:
                    raise ValueError("Token query không hợp lệ.")
                raw = match.group(0)
                if raw in ("AND", "OR", "NOT"):
                    self.tokens.append((raw, raw))
                else:
                    for word in tokenize(raw):
                        self.tokens.append(("leaf", (word,)))
                position += len(raw)
        if len(self.tokens) > 256:
            raise ValueError("Boolean query có quá nhiều token.")
        self.position = 0

    def parse(self):
        """Trả AST; malformed operators/parentheses báo lỗi có giải thích."""
        if not self.tokens:
            raise ValueError("Query không có term.")
        tree = self._or()
        if self.position != len(self.tokens):
            raise ValueError("Parentheses hoặc operator Boolean không hợp lệ.")
        return tree

    def _peek(self):
        return self.tokens[self.position][0] if self.position < len(self.tokens) else None

    def _or(self):
        tree = self._and()
        while self._peek() == "OR":
            self.position += 1
            tree = ("OR", tree, self._and())
        return tree

    def _and(self):
        tree = self._unary()
        while self._peek() in ("AND", "NOT", "leaf", "("):
            if self._peek() == "AND":
                self.position += 1
            tree = ("AND", tree, self._unary())
        return tree

    def _unary(self):
        token = self._peek()
        if token == "NOT":
            self.position += 1
            return ("NOT", self._unary())
        if token == "(":
            self.position += 1
            tree = self._or()
            if self._peek() != ")":
                raise ValueError("Boolean query thiếu dấu đóng ngoặc.")
            self.position += 1
            return tree
        if token == "leaf":
            leaf = self.tokens[self.position][1]
            self.position += 1
            return ("leaf", leaf)
        raise ValueError("Boolean operator cần term hoặc phrase ở bên phải.")


class TextIndex:
    """SPIMI nhỏ theo posting dict; BM25 production và TF-IDF cho bài lab.

    documents là dict có segment_id/text/normalized_text và metadata thời gian.
    Snapshot được cache bởi RetrievalService theo DB data_version.
    """
    def __init__(self, documents: list[dict]):
        self.documents = {row["segment_id"]: row for row in documents}
        self.words = {identifier: tokenize(row["text"]) for identifier, row in self.documents.items()}
        self.frequencies = {identifier: Counter(words) for identifier, words in self.words.items()}
        self.postings: dict[str, set[str]] = defaultdict(set)
        for identifier, frequencies in self.frequencies.items():
            for term in frequencies:
                self.postings[term].add(identifier)
        self.average_length = sum(map(len, self.words.values())) / max(1, len(self.words))

    def _evaluate(self, tree) -> set[str]:
        operator = tree[0]
        if operator == "leaf":
            phrase = tree[1]
            matches = set(self.postings.get(phrase[0], set()))
            for term in phrase[1:]:
                matches.intersection_update(self.postings.get(term, set()))
            if len(phrase) > 1:
                size = len(phrase)
                matches = {identifier for identifier in matches if any(tuple(self.words[identifier][position:position + size]) == phrase for position in range(len(self.words[identifier]) - size + 1))}
            return matches
        if operator == "NOT":
            return set(self.documents).difference(self._evaluate(tree[1]))
        left, right = self._evaluate(tree[1]), self._evaluate(tree[2])
        return left.intersection(right) if operator == "AND" else left.union(right)

    def _positive_terms(self, tree, negated=False) -> list[str]:
        if tree[0] == "leaf":
            return [] if negated else list(tree[1])
        if tree[0] == "NOT":
            return self._positive_terms(tree[1], not negated)
        return self._positive_terms(tree[1], negated) + self._positive_terms(tree[2], negated)

    def search(self, query: str, top_k: int = 100, method: str = "bm25", allowed_ids: set[str] | None = None) -> list[tuple[dict, float]]:
        """Boolean lọc tập ứng viên, sau đó BM25 hoặc cosine TF-IDF xếp hạng.

        Phrase yêu cầu các Unicode token liền nhau. NOT thuần có score=0.
        """
        tree = BooleanParser(query).parse()
        candidates = self._evaluate(tree)
        if allowed_ids is not None:
            candidates.intersection_update(allowed_ids)
        terms = Counter(self._positive_terms(tree))
        count = len(self.documents)
        results = []
        if method not in ("bm25", "tfidf", "boolean"):
            raise ValueError("Text method phải là boolean, bm25 hoặc tfidf.")
        for identifier in candidates:
            frequencies = self.frequencies[identifier]
            score = 0.0
            if method == "bm25":
                for term, query_frequency in terms.items():
                    frequency = frequencies.get(term, 0)
                    df = len(self.postings.get(term, set()))
                    idf = math.log(1 + (count - df + .5) / (df + .5))
                    denominator = frequency + 1.2 * (.25 + .75 * len(self.words[identifier]) / max(self.average_length, 1))
                    score += query_frequency * idf * frequency * 2.2 / max(denominator, 1e-12)
            elif method == "tfidf":
                idf = lambda term: math.log((1 + count) / (1 + len(self.postings.get(term, set())))) + 1
                query_vector = {term: (1 + math.log(frequency)) * idf(term) for term, frequency in terms.items()}
                doc_vector = {term: (1 + math.log(frequency)) * idf(term) for term, frequency in frequencies.items()}
                product = sum(value * doc_vector.get(term, 0) for term, value in query_vector.items())
                denominator = math.sqrt(sum(value * value for value in query_vector.values()) * sum(value * value for value in doc_vector.values()))
                score = product / denominator if denominator else 0
            results.append((self.documents[identifier], float(score)))
        return sorted(results, key=lambda item: (-item[1], item[0]["segment_id"]))[:top_k]


def search_database(db, query: str, source: str, top_k: int = 100, *, video_uids: list[str] | None = None, start_ms: int | None = None, end_ms: int | None = None) -> list[tuple[dict, float]]:
    """Boolean + BM25 qua SQLite FTS5; chỉ materialize top-k segment.

    AST tạo các subquery parameterized, gồm cả NOT thuần và phrase. FTS5 dùng
    unicode61 giữ dấu, còn parser NFC+casefold; không đưa SQL/raw syntax vào MATCH.
    """
    parser = BooleanParser(query)
    tree = parser.parse()
    parameters: list[object] = []

    def predicate(node):
        if node[0] == "leaf":
            parameters.append('"' + " ".join(node[1]) + '"')
            return "t.segment_id IN (SELECT segment_id FROM text_fts WHERE text_fts MATCH ?)"
        if node[0] == "NOT":
            return "NOT (" + predicate(node[1]) + ")"
        return "(" + predicate(node[1]) + " " + node[0] + " " + predicate(node[2]) + ")"

    expression = predicate(tree)
    terms = []

    def positives(node, negative=False):
        if node[0] == "leaf":
            if not negative:
                terms.extend(node[1])
        elif node[0] == "NOT":
            positives(node[1], not negative)
        else:
            positives(node[1], negative)
            positives(node[2], negative)

    positives(tree)
    filters = ["t.source=?", expression]
    condition_values = [source] + parameters
    if video_uids:
        filters.append("t.video_uid IN (" + ",".join("?" for _ in video_uids) + ")")
        condition_values.extend(video_uids)
    if start_ms is not None:
        filters.append("t.end_ms>=?")
        condition_values.append(start_ms)
    if end_ms is not None:
        filters.append("t.start_ms<=?")
        condition_values.append(end_ms)
    if terms:
        rank_query = " OR ".join('"' + term + '"' for term in sorted(set(terms)))
        prefix = "WITH ranks AS (SELECT segment_id, -bm25(text_fts) AS rank_score FROM text_fts WHERE text_fts MATCH ?) "
        statement = prefix + "SELECT t.*,COALESCE(r.rank_score,0) AS rank_score FROM text_segments t LEFT JOIN ranks r ON r.segment_id=t.segment_id WHERE "
        parameters = [rank_query] + condition_values
    else:
        statement = "SELECT t.*,0.0 AS rank_score FROM text_segments t WHERE "
        parameters = condition_values
    statement += " AND ".join(filters) + " ORDER BY rank_score DESC,t.segment_id LIMIT ?"
    parameters.append(top_k)
    return [(row, float(row.pop("rank_score"))) for row in db.rows(statement, parameters)]
