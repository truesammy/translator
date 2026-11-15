"""Manual check that the real providers keep placeholders intact. Makes network calls.

Usage: python scripts/smoke_providers.py   (needs the package installed; set DEEPL_KEY to include the official API)
"""

import asyncio
import os

from translator_bot.languages import get_language
from translator_bot.protect import intact, mask, unmask
from translator_bot.providers.deepl_official import DeepLOfficial
from translator_bot.providers.google_free import GoogleFree

SAMPLE = (
    "# Server update\n"
    "**Maintenance** starts <t:1700000000:F> in <#123>, see [the docs](https://example.com) @everyone\n"
    "- Tom & Jerry say 1 < 2"
)


async def main() -> None:
    providers = [GoogleFree()]
    if os.environ.get("DEEPL_KEY"):
        providers.insert(0, DeepLOfficial(os.environ["DEEPL_KEY"]))
    masked, spans = mask(SAMPLE)
    for provider in providers:
        for code in ("de", "ja", "ar"):
            try:
                (translated,) = await provider.translate([masked], get_language(code), None)
            except Exception as error:
                print(f"[{provider.name} {code}] ERROR {error}")
                continue
            print(f"[{provider.name} {code}] intact={intact(masked, translated)}")
            print(unmask(translated, spans, original=masked))
            print()


asyncio.run(main())
