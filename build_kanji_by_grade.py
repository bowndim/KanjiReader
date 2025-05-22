#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fetch MEXT's 学年別漢字配当表 and build kanji_by_grade.json.

URL current as of May 2025.  If it ever moves, search for
「学年別漢字配当表 2020」 on mext.go.jp and update PAGE_URL.
"""

import json, re, requests
from bs4 import BeautifulSoup

PAGE_URL = (
    "https://www.mext.go.jp/a_menu/shotou/new-cs/youryou/syo/koku/001.htm"
)  # HTML page with the tables

def scrape_mext(url=PAGE_URL) -> dict:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # tables headed “第一学年” … “第六学年”
    kanji_by_grade = {}
    for g, grade in enumerate("一二三四五六", start=1):
        header = soup.find(lambda tag: tag.name in ["h3", "h2"]
                           and f"第{grade}学年" in tag.get_text())
        if not header:
            raise RuntimeError(f"Grade {grade} header not found")

        table = header.find_next("table")
        if not table:
            raise RuntimeError(f"Table for grade {grade} not found")

        chars = []
        for td in table.find_all("td"):
            text = td.get_text(strip=True)
            # the cells often contain multiple kanji separated by spaces or line-breaks
            chars.extend(re.findall(r"[一-鿆]", text))

        # MEXT table already guarantees the right count (80, 160, …)
        kanji_by_grade[str(grade)] = chars

    return kanji_by_grade


def main():
    data = scrape_mext()
    with open("kanji_by_grade.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    print("✅  kanji_by_grade.json written with",
          {g: len(lst) for g, lst in data.items()}, "characters.")


if __name__ == "__main__":
    main()
