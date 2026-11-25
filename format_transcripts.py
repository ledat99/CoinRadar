import os
import glob
import re

def format_text_advanced(text):
    text = text.strip()
    has_punct = bool(re.search(r'[.!?]', text))
    if has_punct:
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÀ-Ỹa-zà-ỹ0-9])', text)
        formatted_paragraphs = []
        current_p = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            current_p.append(s)
            if len(current_p) >= 2 or len(" ".join(current_p)) > 140 or s.endswith('?') or s.endswith('!'):
                formatted_paragraphs.append(" ".join(current_p))
                current_p = []
        if current_p:
            formatted_paragraphs.append(" ".join(current_p))
        return "\n\n".join(formatted_paragraphs) + "\n"
    else:
        words = text.split()
        chunks = []
        cur = []
        for w in words:
            cur.append(w)
            if len(cur) >= 22:
                chunks.append(" ".join(cur))
                cur = []
        if cur:
            chunks.append(" ".join(cur))
        return "\n\n".join(chunks) + "\n"

target_dirs = ["senpaithanh_transcripts", "."]
for d in target_dirs:
    for fpath in glob.glob(os.path.join(d, "*.txt")):
        if "transcript" in fpath or "senpaithanh_transcripts" in fpath:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split('\n')
            if len(lines) <= 5 or any(len(l) > 250 for l in lines):
                formatted = format_text_advanced(content)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(formatted)
                print(f"Re-formatted {fpath}: {formatted.count(chr(10))} lines")
