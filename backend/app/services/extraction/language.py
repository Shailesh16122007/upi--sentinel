"""Language / script detection for evidence text.

Deliberately simple and transparent: Unicode script counts plus small marker-word lists for romanized
Indian languages (Hinglish, Tanglish). It reports what it saw ("Hinglish", "Mixed: English + Hindi")
and how sure it is. It never translates or rewrites the original text.

To add a language: add its Unicode range to SCRIPTS and/or a marker list to ROMANIZED.
"""
from __future__ import annotations

import re

SCRIPTS = {  # name: (range start, end, language name)
    "Devanagari": (0x0900, 0x097F, "Hindi"),
    "Bengali": (0x0980, 0x09FF, "Bengali"),
    "Gurmukhi": (0x0A00, 0x0A7F, "Punjabi"),
    "Gujarati": (0x0A80, 0x0AFF, "Gujarati"),
    "Tamil": (0x0B80, 0x0BFF, "Tamil"),
    "Telugu": (0x0C00, 0x0C7F, "Telugu"),
    "Kannada": (0x0C80, 0x0CFF, "Kannada"),
    "Malayalam": (0x0D00, 0x0D7F, "Malayalam"),
}

ROMANIZED = {
    # language: (label when mixed with English, marker words)
    "Hindi": ("Hinglish", set("""hai hain nahi nahin nhi kya karo kariye kijiye karna karein kar raha rahi rahe tha thi the
        ho hoga hogi jayega jaega jayegi jaayega jaldi abhi turant aap aapka aapke aapko apna apne mera mere meri tum tumhara
        hum humara bhai bhaiya ji sahab bol bola boli bolo bata batao bata do bataiye bhejo bhej daalo dalo paise paisa rupaye
        wapas milega milegi lagi lag gaya gayi kyun kyunki lekin aur bhi sirf kuch koi kaise kab yahan wahan accha theek
        chahiye samjho samajh dekho suno haan matlab warna toh kat band""".split())),
    "Tamil": ("Tanglish", set("""panna pannunga pannanga panniten sollu sollunga solli sonnanga enna illa illai irukku iruku
        vanga ponga venum vendam unga ungal naan neenga avanga ithu athu inga anga epdi eppadi ippo udane kaasu panam
        irundhu pesuren pesaren aayidum aagidum anuppunga""".split())),
}
EN_MARKERS = set("""the is are was were you your yours this that please will would have has had and with from for to of
    in on at be been account bank payment debited credited amount sent received transaction dear customer call""".split())

WORD = re.compile(r"[A-Za-z]+")


def detect(text: str) -> dict:
    text = text or ""
    counts: dict[str, int] = {}
    latin = 0
    for ch in text:
        o = ord(ch)
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin += 1
            continue
        for name, (a, b, _) in SCRIPTS.items():
            if a <= o <= b:
                counts[name] = counts.get(name, 0) + 1
                break
    words = [w.lower() for w in WORD.findall(text)]
    n = len(words) or 1
    en = sum(w in EN_MARKERS for w in words)
    roman = {lang: sum(w in markers for w in words) for lang, (_, markers) in ROMANIZED.items()}
    letters = latin + sum(counts.values())
    if letters < 6:
        return {"label": "Not enough text", "confidence": "Low", "scripts": counts, "basis": "Too little text to tell."}

    langs: list[str] = []
    basis = []
    for name, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        if c / letters >= 0.08:
            langs.append(SCRIPTS[name][2])
            basis.append(f"{name} script ({c} characters)")
    romanized_label = None
    for lang, hits in roman.items():
        if hits >= 2 and hits / n >= 0.08:
            romanized_label = ROMANIZED[lang][0]
            basis.append(f"{hits} common romanized {lang} words")
            break
    english = en >= 2 and en / n >= 0.08
    if english:
        basis.append(f"{en} common English words")

    if romanized_label and not langs:
        label = romanized_label
    elif langs and (english or romanized_label or latin / letters > 0.3):
        label = "Mixed: " + " + ".join((["English"] if english or latin / letters > 0.3 else []) + langs)
    elif langs:
        label = langs[0] if len(langs) == 1 else "Mixed: " + " + ".join(langs)
    elif english:
        label = "English"
    else:
        label = "Unknown (Latin script)"
    strong = (romanized_label and roman.get(next(k for k, v in ROMANIZED.items() if v[0] == romanized_label), 0) >= 4) or \
        any(c >= 30 for c in counts.values()) or en >= 6
    return {"label": label, "confidence": "Medium" if strong else "Low", "scripts": counts,
            "basis": "; ".join(basis) or "Latin script only", "word_count": len(words)}
