import os, re, json, asyncio, io, pathlib, datetime, requests
from pathlib import Path
from PIL import Image

import openai, jinja2, fugashi, pykakasi
from ebooklib import epub
from aiohttp import ClientSession
from jinja2 import Environment, FileSystemLoader, select_autoescape

import unicodedata as ud

#from playwright.async_api import async_playwright
import tempfile, jaconv

import base64
# ---------- paths ----------
BASE = Path(__file__).parent
KANJI_JSON = BASE / "kanji_by_grade.json"
TEMPLATE_DIR = BASE / "prompts" 
OUTPUT_DIR = BASE.parent / "books"
DBG_DIR  = BASE.parent / "ai_debug"
DBG_DIR.mkdir(exist_ok=True)

# ---------- static data ----------
OPENAI_MODEL_TEXT = "gpt-4o-mini"
OPENAI_MODEL_IMAGE = "dall-e-3"
openai.api_key = os.getenv("OPENAI_API_KEY")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR),autoescape=select_autoescape())
KANJI = json.load(open(KANJI_JSON, encoding="utf-8"))
kakasi = pykakasi.kakasi()
CHAR_THRESHOLD = 500   # tweak as taste
# romaji vowel → hiragana we want to append
VOWEL2HIRA = {"a": "あ", "i": "い", "u": "う", "e": "い", "o": "う"}
DEBUG_AI = False                    # switch to False in production
MAX_PICS = 3
MAX_RETRY_SPLIT = 2 

HTML_TMPL = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<style>
@font-face{{
  font-family: "NotoSerifJP";
  src: local("Noto Serif JP Regular"),
       url("https://fonts.gstatic.com/ea/notoserifjpv8/NotoSerifJP-Regular.otf")
       format("opentype");
}}
html{{
  writing-mode: vertical-rl;
  font-family: "NotoSerifJP", serif;
  font-size: 1.0rem;
  margin-block: 15mm;
  margin-inline: 10mm;
  line-height: 1.6;
  inline-size: 26rem; 
  margin-inline-end:4mm;   
  -webkit-line-break: strict; line-break: strict;
}}
body{{margin:0}}
section.side{{
  /* Lay out horizontally just for this page */
  writing-mode:horizontal-tb;   /* flex axis is now true L→R */
  display:flex;
  flex-direction:row-reverse;   /* image left, text right */
  page-break-after:always;
  height:85vh;                 /* fill page during PDF print */
  align-items:flex-start;
  gap: 4mm; 
}}
section.side .text{{
  writing-mode:vertical-rl;     /* restore tategaki for text */
  flex:1 1 50%;
  margin-inline-end:5mm;        /* gap between img and text */
  inline-size: 26rem;   
}}
section.side img{{
  flex:1 1 50%;
  max-block-size: 85vh;   /* never exceed 80% page height */
  object-fit: contain;    /* keep aspect ratio */
  direction:rtl;
  margin-inline-end:4mm;
}}
section.picture img{{
  max-block-size: 85hh;   /* full-page picture, but still leaves top/bottom white-space */
  object-fit: contain;
}}

/* solo text & full-page picture pages */
section.solo, section.picture{{ break-after:page; }}
section.picture img{{ max-width:100%; height:auto; }}
ruby{{ ruby-position: over; }}
img{{ max-width: 100%; break-after: page; }}
div.pagebreak{{ break-after: page; }}
@media print and (-webkit-min-device-pixel-ratio:0){{
  div.pagebreak{{
    break-after: auto;          /* neutralise the buggy value   */
  }}
}}
</style>
</head>
<body>
{content}
</body></html>
"""


# ---------- helpers ----------
def make_tagger(dic: str = "lite") -> fugashi.GenericTagger:
    """
    dic = "lite"  → use the 6 MB unidic_lite dictionary
    dic = "full"  → use the big unidic dictionary
    """
    if dic == "lite":
        import unidic_lite
        dicdir = pathlib.Path(unidic_lite.DICDIR)
        rcfile = dicdir / "mecabrc"          # file exists in the wheel
        os.environ["MECABRC"] = str(rcfile)  # ← add this line
        # either give both -r and -d, or just -d (MeCab reads env var)
        return fugashi.GenericTagger(f'-r "{rcfile}" -d "{dicdir}"')        
        #dicdir = pathlib.Path(unidic_lite.DICDIR)      # .../unidic_lite/dicdir
        # lite wheel already bundles a mini mecabrc → GenericTagger() is enough
        #return fugashi.GenericTagger(f'-d "{dicdir}"')

    elif dic == "full":
        import unidic
        dicdir  = pathlib.Path(unidic.DICDIR)          # .../unidic/dicdir
        rcfile  = dicdir / "mecabrc"
        os.environ["MECABRC"] = str(rcfile)            # ensure the right rc
        return fugashi.GenericTagger(f'-d "{dicdir}"')

    else:
        raise ValueError("dic must be 'lite' or 'full'")
tagger = make_tagger("lite")
        
def as_data_uri(img_bytes: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"
    
def kata2hira_fix(text_kata: str) -> str:
    """
    Convert a katakana string to hiragana, expanding 'ー' to the
    appropriate vowel (あ, い, う, い, or う for お-row).
    """
    hira = jaconv.kata2hira(text_kata)
    out = []
    for ch in hira:
        if ch == "ー":
            if not out:        # leading 'ー' – ignore
                continue
            prev = out[-1]
            # Convert prev kana to romaji and grab last vowel
            r = kakasi.convert(prev)[0]["hepburn"]
            vowel = next((c for c in reversed(r) if c in "aiueo"), "u")
            out.append(VOWEL2HIRA[vowel])
        else:
            out.append(ch)
    return "".join(out)
    
def plain_len(html: str) -> int:
    "Length of visible text, no tags."
    return len(re.sub(r"<[^>]+>", "", html))
    
def page_html(text_html: str, img_name: str | None, char_len: int) -> str:
    if img_name and char_len < CHAR_THRESHOLD:
        # side-by-side page
        return f"""
                <section class="side">
                  <div class="text">{text_html}</div>
                  <img src="{img_name}" alt="">
                </section>"""
    else:
        # text page, then (maybe) image page
        html = f"<section class='solo'>{text_html}</section>"
        if img_name:
            html += f"<section class='picture'><img src='{img_name}' alt=''></section>"
        return html
        
def romaji_slug(text: str, maxlen: int = 50) -> str:
    """
    Convert Japanese or mixed text to a filesystem-safe romaji slug.
    - Hiragana/Kanji/Katakana → romaji (lowercase)
    - ASCII letters/digits kept as-is
    - Everything else → underscore
    """
    roma = "".join(item["hepburn"] for item in kakasi.convert(text))
    roma = re.sub(r"[^A-Za-z0-9]+", "_", roma).strip("_").lower()
    return roma[:maxlen] or "untitled"
    
def is_kana(ch: str) -> bool:
    return "HIRAGANA" in ud.name(ch, "") or "KATAKANA" in ud.name(ch, "")
    
def build_full_html(html_pieces:list[str])->str:
    joined = ""
    for block in html_pieces:
        joined += f"<div>{block}</div><div class='pagebreak'></div>"
    return HTML_TMPL.format(content=joined)

#async def html_to_pdf(html:str, outfile:str, page_size:str="A4"):
#    async with async_playwright() as p:
#        browser = await p.chromium.launch()
#        page = await browser.new_page()
#        await page.set_content(html, wait_until="networkidle")
#        await page.pdf(path=outfile,
#                       format=page_size,
#                       margin={"top":"0","bottom":"0","left":"0","right":"0"},
#                       print_background=True)
#        await browser.close()
        
def is_kanji(c):
    return "CJK UNIFIED" in ud.name(c, "")

def grade_of(ch):
    if not is_kanji(ch):
        return None
    for g, lst in KANJI.items():
        if ch in lst:
            return int(g)
    return 99  

def sanitize(text:str, max_grade:int)->str:
    """
    Replace every token that contains a kanji above `max_grade`
    with its hiragana reading.
    """
    out = []
    for tok in tagger(text):
        if any(is_kanji(ch) and grade_of(ch) and grade_of(ch) > max_grade
            for ch in tok.surface):
                if len(tok.feature) > 9 and tok.feature[9]:
                    reading = kata2hira_fix(tok.feature[9])
                else:
                    reading = "".join(m["hira"] for m in kakasi.convert(tok.surface))     
                #reading = reading.lower().replace("ー","")            
                out.append(reading)
        else:
            out.append(tok.surface)
    return "".join(out)
    
def inject_ruby(text: str, grade: int) -> str:
    grade_set = set(KANJI[str(grade)])
    out = []
    for tok in tagger(text):
        surf = tok.surface
        # Do we need ruby at all?
        if not any(c in grade_set for c in surf):
            out.append(surf)
            continue

        # Get reading in hiragana
        if len(tok.feature) > 9 and tok.feature[9]:
            reading = kata2hira_fix(tok.feature[9])
        else:
            reading = "".join(m["hira"] for m in kakasi.convert(surf))  

        # --- NEW: strip okurigana that match reading tail ---
        i = 1
        while i <= len(surf) and i <= len(reading):
            if is_kana(surf[-i]) and surf[-i] == reading[-i]:
                i += 1
            else:
                break
        okuri_len = i - 1          # number of kana chars to strip
        if okuri_len:
            core_surf   = surf[:-okuri_len]
            core_read   = reading[:-okuri_len]
            okurigana   = surf[-okuri_len:]
        else:
            core_surf, core_read, okurigana = surf, reading, ""

        # Guard: avoid empty ruby (rare OOV edge)
        if not core_read:
            out.append(surf)
        else:
            ruby = f"<ruby>{core_surf}<rt>{core_read}</rt></ruby>{okurigana}"
            out.append(ruby)
    return "".join(out)

def validate_story(txt:str, grade:int, kanji:list[str], min_freq:int):
    counts = {k:0 for k in kanji}
    for ch in txt:
        g = grade_of(ch)
        if g and g > grade:
            raise ValueError(f"Disallowed kanji {ch}")
        if ch in counts:
            counts[ch]+=1
    for k,c in counts.items():
        if c < min_freq:
            raise ValueError(f"{k} appears {c} < required {min_freq}")

def dump_ai(kind: str, slug: str, resp):
    """
    kind  : 'story', 'split', 'image'
    slug  : romaji slug of the book
    resp  : openai object (ChatCompletion or ImageResponse)
    """
    if not DEBUG_AI:           # quick global off switch
        return
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = DBG_DIR / f"{slug}_{kind}_{ts}.json"

    # serialise openai response → JSON
    if hasattr(resp, "model_dump_json"):       # v1 client
        raw = resp.model_dump()
    else:                                      # fallback for older
        raw = resp

    with open(fname, "w", encoding="utf-8") as fp:
        json.dump(raw, fp, ensure_ascii=False, indent=2)
    print(f"📝 debug: saved {fname.relative_to(DBG_DIR.parent)}")
def dump_prompt(kind: str, slug: str, prompt: str):
    """
    kind  : 'story', 'split', 'imageN'
    slug  : book slug (roman characters)
    prompt: raw text you send to OpenAI
    """
    if not DEBUG_AI:
        return
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = DBG_DIR / f"{slug}_{kind}_PROMPT_{ts}.txt"
    with open(fname, "w", encoding="utf-8") as fp:
        fp.write(prompt)
    print(f"📝 debug: saved {fname.relative_to(DBG_DIR.parent)}")
    
def halve_image(img_bytes: bytes) -> bytes:
    """
    Return a new JPEG at half the width/height of the original.
    Keeps EXIF orientation; quality=85 is a good compromise.
    """
    with Image.open(io.BytesIO(img_bytes)) as im:
        w, h = im.size
        im = im.resize((w // 2, h // 2), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85, dpi=(72, 72), optimize=True)
        return buf.getvalue()    
        
def generate_series_via_chat(prompts: list[str], style: str):
    """
    prompts : list of scene prompts (already include [TAGS] + style keyword)
    Returns : list of (prompt, jpeg-bytes)
    """
    messages = [
        {"role": "system",
         "content":
            "You are an illustration model. "
            "Return each image as JSON: {\"url\":\"...\"}. "
            "Use the user's prompt exactly, do not invent new details."}
    ]

    results = []
    for p in prompts:
        messages.append({"role": "user", "content": p})
        resp = openai.chat.completions.create(
            model="dall-e-3",
            messages=messages
        )
        messages.append(resp.choices[0].message)        # keep context

        # extract URL from assistant JSON
        data = json.loads(resp.choices[0].message.content)
        url  = data["url"]
        img_bytes = requests.get(url).content
        results.append((p, img_bytes))

    return results  
    
async def load_images(n:int)->list[bytes]:
    data=[]
    for i in range(1,n+1):
        path = BASE / IMG_PATTERN.format(index=i)
        if not path.exists():
            raise FileNotFoundError(path)
        data.append(path.read_bytes())
    return data

async def download_image(url, session):
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.read()
    

# ---------- main test-driver ----------
async def make_reader(
    *,
    grade:int,
    kanji:list[str],
    min_freq:int,
    wc_range:tuple[int,int],
    n_pics:int,
    style:str,
    idea:str|None=None,
    out_dir=OUTPUT_DIR
):
    # Step I : load story.txt
    story_prompt = env.get_template("story.j2").render(
        grade=grade, kanji_list=kanji, min_freq=min_freq,
        wc_min=wc_range[0], wc_max=wc_range[1], idea=idea
    )
    resp_story = openai.chat.completions.create(
        model=OPENAI_MODEL_TEXT,
        messages=[{"role":"user","content":story_prompt}],
        temperature=0.7
    )
    data = json.loads(resp_story.choices[0].message.content)
    title       = data["title"].strip()
    story_raw   = data["story"].split("###END###")[0].strip()
    story_clean = sanitize(story_raw, grade)
    #validate_story(story_clean, grade, kanji, min_freq)
    slug      = romaji_slug(title)
    filename  = f"{slug}.epub"
    pdf_file  = f"{slug}.pdf"
    dump_prompt("story", slug, story_prompt)     
    dump_ai("story", slug, resp_story)    

    # Step II : load split.json
    n_pics = MAX_PICS if n_pics > MAX_PICS else n_pics    
    if n_pics > 0:
        
        split_prompt = env.get_template("split.j2").render(
            pieces=n_pics, style=style, story=story_clean
        )
        dump_prompt("split", slug, split_prompt)     
      
        for attempt in range(MAX_RETRY_SPLIT + 1):    
            resp_split = openai.chat.completions.create(
                model=OPENAI_MODEL_TEXT,
                messages=[{"role":"user","content":split_prompt}],
                temperature=0.5
            ) 
            dump_ai("split", slug, resp_split)    
            #pieces_obj = json.load(open(SPLIT_FILE, encoding="utf-8"))
            pieces_obj = json.loads(resp_split.choices[0].message.content )
            pieces = pieces_obj["pieces"]               # [{text:, prompt:}, …]
            expected = n_pics
                # ---------- validation ----------
            if len(pieces) == expected:
                break  # ✓ good JSON length
            elif attempt < MAX_RETRY_SPLIT:
                print(f"⚠ Split length {len(pieces)} ≠ {expected}. Retrying…")
            else:
                raise ValueError(f"Split length {len(pieces)} ≠ {expected} after retries")

        # Step III : load images
        #prompts = [p["prompt"] for p in pieces]
        #style_kw = style if style else "Colored Pencil sketch"
        #prompts = [f"{pr}, {style_kw}" for pr in prompts]   # guarantee keyword

        #characters = pieces_obj["characters"]          # from splitter JSON
        #valid_tags = {c["tag"] for c in characters}    # e.g. {"[RIN]", "[TAROU]"}

        #prompts = [p["prompt"] for p in pieces]
        #prompts = [f"{{{{'Art style': {style}}}, {pr}}}" for pr in prompts]  
        #for p in pieces:
        #    if style.lower() not in p["prompt"].lower():
        #        raise ValueError("style missing")
        #    if not any(tag in p["prompt"] for tag in valid_tags):
        #        raise ValueError("tag missing")


        #imgs = []
        #for pr, img_bytes in generate_series_via_chat(prompts, style_kw):
        #    dump_prompt(f"image{len(imgs)+1}", slug, pr)    # debug
        #    imgs.append(img_bytes)
        
        imgs = []
        for idx, p in enumerate(pieces, 1):
            prompt = f"{{{{'Art style': {style}}}, {p['prompt']}}}"
            dump_prompt(f"image{idx}", slug, prompt)

            gen = openai.images.generate(
                model="dall-e-3",
                prompt=prompt, n=1, size="1024x1024"
            )
            dump_ai(f"image{idx}", slug, gen)
            img_bytes = requests.get(gen.data[0].url).content
            imgs.append(img_bytes)        
        #img_tasks = []
        #async with ClientSession() as session:
        #    for i, p in enumerate(pieces, 1):
        #        img_prompt = p["prompt"]
        #        dump_prompt(f"image{i}", slug, img_prompt)            
        #        gen = openai.images.generate(
        #            model=OPENAI_MODEL_IMAGE,
        #            prompt=img_prompt,
        #            n=1, size="1024x1024"
        #        )
        #        dump_ai(f"image{i}", slug, gen)                
        #        url = gen.data[0].url
        #        img_tasks.append(download_image(url, session))
        #    imgs = await asyncio.gather(*img_tasks) 
    else:
        pieces = [{"index": 1, "text": story_clean, "prompt": ""}]
        imgs = [None]
    #imgs = [None] if len(pieces) == 1 else await load_images(len(pieces))

    # Step IV : ruby injection
    html_pieces = [inject_ruby(sanitize(p["text"], grade), grade) for p in pieces]

    # Step V : build EPUB (vertical-rl)
    book = epub.EpubBook()
    book.direction = 'rtl'       
    book.set_identifier("kanji_reader_" + slug)
    book.set_title(title)
    book.add_author("Offline AI")

    css = epub.EpubItem(
        uid="style", file_name="style.css", media_type="text/css",
        content="""body{writing-mode:vertical-rl;font-family:"Noto Serif JP";}
img{max-width:100%;}div.pagebreak{page-break-after:always;}"""
    )
    book.add_item(css)

    spine = []
    pdf_pages = []  
    for i, (html, img_bytes) in enumerate(zip(html_pieces, imgs), 1):
        # 1️ always add the picture to manifest
        if img_bytes is not None:
            img_uid  = f"img{i}"
            img_name = f"{img_uid}.jpg"
            img_item = epub.EpubItem(
                uid=img_uid, file_name=img_name,
                media_type="image/jpeg", content=img_bytes
            )
            book.add_item(img_item)

            epub_src = img_name
            sm_bytes = halve_image(img_bytes) 
            data_uri = as_data_uri(sm_bytes)
        else:
            img_name = epub_src = data_uri = None
        
        # 2️ Decide layout
        short = plain_len(html) < CHAR_THRESHOLD
        pages_html = []

        if short and img_bytes is not None:
            # side-by-side single page
            sec = f"""
                <section class="side">
                <div class="text">{html}</div>
                <img src="{data_uri}" alt="">
                </section>"""
            epub_sec = sec.replace(data_uri, epub_src)
            # one XHTML file
            page = epub.EpubHtml(title=f"p{i}", file_name=f"p{i}.xhtml", lang="ja")
            page.content = epub_sec
            page.add_item(css)
            book.add_item(page)
            spine.append(page)
            pdf_pages.append(sec)
        else:
            # text-only (solo) page
            txt_sec  = f"<section class='solo'>{html}</section>"
            txt_page = epub.EpubHtml(title=f"p{i}_txt", file_name=f"p{i}_txt.xhtml", lang="ja")
            txt_page.content = txt_sec
            txt_page.add_item(css)
            book.add_item(txt_page)
            spine.append(txt_page)
            pdf_pages.append(txt_sec)

            # optional picture page
            if img_bytes is not None:
                img_sec  = f"<section class='picture'><img src='{data_uri}' alt=''></section>"
                img_page = epub.EpubHtml(title=f"p{i}_img", file_name=f"p{i}_img.xhtml", lang="ja")
                img_page.content = img_sec.replace(data_uri, epub_src)   # EPUB src
                img_page.add_item(css)
                book.add_item(img_page)
                spine.append(img_page)
                pdf_pages.append(img_sec)
        
        pdf_pages.extend(pages_html)
        # 3️ Emit each <section> as its own XHTML file & add to spine
        for j, sec in enumerate(pages_html, 1):
            file_name = f"p{i}_{j}.xhtml"
            page = epub.EpubHtml(title=f"p{i}_{j}", file_name=file_name, lang="ja")
            page.content = sec
            page.add_item(css)
            book.add_item(page)
            spine.append(page)


    book.spine = ["nav"] + spine
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())

    epub_path = out_dir / filename
    epub.write_epub(epub_path, book)
    print("✅ EPUB written to", epub_path)
    
    # ─ Step VI : PDF ─
    #full_html = build_full_html(html_pieces)
    full_html = build_full_html(pdf_pages)
    html_file = f"{slug}.html"
    html_path = out_dir / html_file
    with open(html_path, "w", encoding="utf-8") as fp:
        fp.write(full_html)   
    #pdf_path = out_dir / pdf_file      
    #this isnt neccessary
    #await html_to_pdf(full_html, pdf_path)

    return (epub_path, html_path)


# ---------- quick manual test ----------
if __name__ == "__main__":
    import asyncio
    asyncio.run(make_reader(
        grade=3,
        kanji=["海","魚","強"],
        min_freq=5,
        wc_range=(2000, 3000),
        n_pics=0,
        style="Colored Pencil sketch",
        idea=None
    ))
