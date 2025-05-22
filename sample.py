import asyncio, reader

async def run():
    fname, story, pieces = await reader.make_reader(
        grade=3,
        kanji=["泳","速","深"],
        min_freq=3,
        wc_range=(600,800),
        n_pics=3,
        style="water-color children’s picture-book",
        idea="A summer adventure by the river"
    )
    print("EPUB saved as", fname)

asyncio.run(run())
