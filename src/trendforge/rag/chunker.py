"""智能 Chunk — 结构化层级切分

切分策略（按优先级）：
  标题 → 一级标题(h1) → 二级标题(h2) → 三级(h3) → 自然段(p) → 列表(li)
    → 若单个块仍超 max_tokens，按句子切，再按 token 窗口切（带 overlap）

每个 chunk：
  - content: 文本（含所属标题作为上下文前缀）
  - token_count: 估算 token 数
  - section_path: 结构路径，如 "多模态推理 > 性能基准"

目标 300~500 token / 段，overlap 50~80 token（见 config）。
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup
from config import settings


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文 ~1.5 字/token，英文 ~4 字符/token"""
    if not text:
        return 0
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cn
    return int(cn / 1.5 + other / 4)


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


# 块类型与对应层级
_BLOCK_TAGS = [("h1", 1), ("h2", 2), ("h3", 3), ("h4", 4), ("p", 0), ("li", 0), ("blockquote", 0)]


def _extract_blocks(html_or_text: str, title: str) -> list[dict]:
    """从 HTML/纯文本提取结构化块列表。每块: {text, level, path}"""
    # 尝试作为 HTML 解析；若无标签 bs4 也能当纯文本处理
    soup = BeautifulSoup(html_or_text, "lxml")
    blocks: list[dict] = []

    # 标题作为第一个块（level -1 表示文章标题）
    if title:
        blocks.append({"text": _clean_text(title), "level": -1, "path": "title"})

    section_stack: list[tuple[int, str]] = []  # [(level, heading_text), ...]

    for tag in soup.find_all([b[0] for b in _BLOCK_TAGS]):
        tag_name = tag.name
        text = _clean_text(tag.get_text(" ", strip=True))
        if not text or len(text) < 2:
            continue
        level = next(l for n, l in _BLOCK_TAGS if n == tag_name)

        if level > 0:  # 标题
            # 维护 section 栈
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, text))
            path = " > ".join(s[1] for s in section_stack)
            blocks.append({"text": text, "level": level, "path": path, "is_heading": True})
        else:  # 段落/列表
            path = " > ".join(s[1] for s in section_stack) if section_stack else ""
            blocks.append({"text": text, "level": 0, "path": path, "is_heading": False})

    # 若 bs4 没解析出任何结构（纯文本），按段落切
    if len(blocks) <= 1:
        raw = _clean_text(soup.get_text(" ", strip=True)) or _clean_text(html_or_text)
        for para in re.split(r"\n{2,}|(?<=[。！？.!?])\s+", raw):
            para = para.strip()
            if len(para) > 10:
                blocks.append({"text": para, "level": 0, "path": "", "is_heading": False})
    return blocks


def _split_long_block(text: str, target: int, max_t: int, overlap: int) -> list[str]:
    """单个超长块按句子+token 窗口切分（带 overlap）"""
    # 先按句子切
    sentences = re.split(r"(?<=[。！？!?\.])\s+", text)
    sentences = [s for s in sentences if s.strip()]
    if not sentences:
        return []
    pieces: list[str] = []
    buf, buf_tok = [], 0
    for s in sentences:
        st = estimate_tokens(s)
        if buf_tok + st > max_t and buf:  # 超限，先关闭
            pieces.append(" ".join(buf))
            # overlap：保留尾部
            tail_tok, tail_buf = 0, []
            for b in reversed(buf):
                bt = estimate_tokens(b)
                if tail_tok + bt > overlap:
                    break
                tail_buf.insert(0, b)
                tail_tok += bt
            buf, buf_tok = tail_buf, tail_tok
        buf.append(s)
        buf_tok += st
        if buf_tok >= target:  # 达到目标，关闭
            pieces.append(" ".join(buf))
            tail_tok, tail_buf = 0, []
            for b in reversed(buf):
                bt = estimate_tokens(b)
                if tail_tok + bt > overlap:
                    break
                tail_buf.insert(0, b)
                tail_tok += bt
            buf, buf_tok = tail_buf, tail_tok
    if buf:
        pieces.append(" ".join(buf))
    return pieces


def smart_chunk(
    title: str,
    full_text: str,
    target: int | None = None,
    min_tokens: int | None = None,
    overlap: int | None = None,
    max_tokens: int | None = None,
) -> list[dict]:
    """智能切分。返回 [{content, token_count, section_path}, ...]"""
    target = target or settings.chunk_target_tokens
    min_tokens = min_tokens or settings.chunk_min_tokens
    overlap = overlap or settings.chunk_overlap_tokens
    max_tokens = max_tokens or settings.chunk_max_tokens

    blocks = _extract_blocks(full_text, title)
    if not blocks:
        return []

    chunks: list[dict] = []
    # 当前 chunk 的缓冲：文本片段列表 + 当前 section path
    buf: list[str] = []
    buf_tok = 0
    cur_path = ""
    cur_heading_prefix = ""  # 当前 section 的标题文本，作为 chunk 上下文

    def flush():
        nonlocal buf, buf_tok
        if not buf:
            return
        text = " ".join(buf).strip()
        if not text:
            buf, buf_tok = [], 0
            return
        # 若仍超 max，二次切分
        if estimate_tokens(text) > max_tokens:
            for piece in _split_long_block(text, target, max_tokens, overlap):
                if estimate_tokens(piece) >= 5:
                    chunks.append({"content": piece, "token_count": estimate_tokens(piece), "section_path": cur_path})
        else:
            chunks.append({"content": text, "token_count": estimate_tokens(text), "section_path": cur_path})
        buf, buf_tok = [], 0

    for blk in blocks:
        if blk.get("is_heading"):
            # 遇到新标题：先 flush 当前缓冲
            flush()
            cur_path = blk["path"]
            cur_heading_prefix = blk["text"]
            # 标题本身作为块加入（短）
            buf.append(blk["text"])
            buf_tok = estimate_tokens(blk["text"])
            continue
        # 段落/列表
        if blk["path"] and blk["path"] != cur_path:
            flush()
            cur_path = blk["path"]
        piece = blk["text"]
        pt = estimate_tokens(piece)
        # 若单块就超 max，单独切
        if pt > max_tokens:
            flush()
            for sub in _split_long_block(piece, target, max_tokens, overlap):
                if estimate_tokens(sub) >= 5:
                    chunks.append({"content": sub, "token_count": estimate_tokens(sub), "section_path": cur_path})
            continue
        # 累积到目标即 flush（带 overlap 上下文）
        if buf_tok + pt > max_tokens and buf:
            flush()
            # overlap：把上一个 chunk 尾部作为新 chunk 上下文
            if chunks:
                last = chunks[-1]["content"]
                last_words = last.split()
                tail, tail_tok = [], 0
                for w in reversed(last_words):
                    wt = estimate_tokens(w)
                    if tail_tok + wt > overlap:
                        break
                    tail.insert(0, w)
                    tail_tok += wt
                if tail:
                    buf = [" ".join(tail)]
                    buf_tok = tail_tok
        buf.append(piece)
        buf_tok += pt
        if buf_tok >= target:
            flush()
    flush()

    # 合并过短的 chunk（< min_tokens）到前一个
    merged: list[dict] = []
    for c in chunks:
        if c["token_count"] < min_tokens and merged:
            prev = merged[-1]
            prev["content"] = prev["content"] + " " + c["content"]
            prev["token_count"] = estimate_tokens(prev["content"])
        else:
            merged.append(c)

    # 每个 chunk 前面加上文章标题作为上下文（提升检索召回）
    title_clean = _clean_text(title)
    for c in merged:
        if title_clean and not c["content"].startswith(title_clean):
            c["content"] = f"[{title_clean}] {c['content']}"
            c["token_count"] = estimate_tokens(c["content"])
    return merged
