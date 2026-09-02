"""Prompt sets, one per note language.

The instruction language matches the output language deliberately: writing
English instructions and asking for Lithuanian output makes the model drift
between the two mid-note. The transcript language is stated separately, because
a Lithuanian lecture summarised into an English note needs the English prompt
to say where the text came from.
"""

LANG_NAMES = {"en": "English", "lt": "Lithuanian"}
LANG_NAMES_LT = {"en": "anglų", "lt": "lietuvių"}

PROMPTS = {
    "en": {
        "section": """You are given part of a university lecture transcript in {src}.
It came from speech recognition, so expect disfluencies and occasional wrong
words.

Write a factual summary of what is actually taught in this part. Cover the
concepts introduced, any definitions given, and the reasoning or examples used.
Do not invent structure that is not there. Do not add an introduction or a
conclusion. If a passage is too garbled to interpret, ignore it rather than
guessing.

TRANSCRIPT PART:
{chunk}""",

        "combine": """Below are sequential summaries of one university lecture, transcribed
from {src}.

Write a single study note in English, in markdown, with these sections and
nothing else:

## Summary
Four to six sentences on what the lecture was about and where it ended up.

## Key concepts
Each concept with a one-line explanation in the lecturer's terms.

## Detail
The substance, in the order it was taught, as prose with subheadings.

## Open questions
Anything left unresolved, or flagged as needing further reading. Omit the
section if there was nothing.

Base it only on what is below. Do not invent examples or citations. Keep
technical terms in their original form where translating them would lose
meaning. Output raw markdown. Do not wrap your answer in a code fence.

SECTION SUMMARIES:
{sections}""",

        "topic": """Below is a summary of one university lecture.

Reply with a short title for it: three to seven words, naming the specific
subject matter. No quotes, no punctuation at the end, no prefix such as
"Lecture on". Reply with the title and nothing else.

{note}""",
    },

    "lt": {
        "section": """Pateikta universiteto paskaitos transkripcijos dalis {src_lt} kalba.
Ji gauta iš kalbos atpažinimo sistemos, todėl pasitaiko nesklandumų ir
klaidingai atpažintų žodžių.

Parašyk dalykišką santrauką to, kas šioje dalyje iš tikrųjų dėstoma. Aprašyk
pristatytas sąvokas, pateiktus apibrėžimus ir naudotus argumentus ar pavyzdžius.
Nekurk struktūros, kurios nėra. Nerašyk įžangos ar išvadų. Jei kuri nors vieta
per daug iškraipyta, kad ją būtų galima suprasti, praleisk ją, o ne spėk.

TRANSKRIPCIJOS DALIS:
{chunk}""",

        "combine": """Žemiau iš eilės pateiktos vienos universiteto paskaitos dalių
santraukos. Paskaita transkribuota iš {src_lt} kalbos.

Parašyk vieną mokymosi konspektą lietuvių kalba, markdown formatu, su šiais
skyriais ir nieko daugiau:

## Santrauka
Keturi–šeši sakiniai apie tai, kas buvo dėstoma ir prie ko prieita.

## Pagrindinės sąvokos
Kiekviena sąvoka su vienos eilutės paaiškinimu dėstytojo terminais.

## Turinys
Esmė ta pačia tvarka, kuria buvo dėstoma, ištisiniu tekstu su paantraštėmis.

## Neatsakyti klausimai
Kas liko neatsakyta arba paminėta kaip reikalaujantis papildomo skaitymo.
Praleisk šį skyrių, jei tokių dalykų nebuvo.

Remkis tik tuo, kas pateikta žemiau. Nekurk pavyzdžių ar šaltinių. Terminus,
kurių vertimas prarastų prasmę, palik originalia forma. Rašyk gryną markdown.
Neapvyniok atsakymo į kodo bloką.

DALIŲ SANTRAUKOS:
{sections}""",

        "topic": """Žemiau pateikta vienos universiteto paskaitos santrauka.

Atsakyk trumpu pavadinimu: nuo trijų iki septynių žodžių, įvardijančių konkrečią
temą. Be kabučių, be skyrybos ženklo pabaigoje, be priešdėlio „Paskaita apie".
Atsakyk tik pavadinimu ir nieko daugiau.

{note}""",
    },
}


def get(note_lang, src_lang):
    """Prompt set for the note language, with the transcript language filled in.
    Falls back to English for any language without a translated set."""
    p = PROMPTS.get(note_lang, PROMPTS["en"])
    return {
        k: v.replace("{src_lt}", LANG_NAMES_LT.get(src_lang, src_lang))
            .replace("{src}", LANG_NAMES.get(src_lang, src_lang))
        for k, v in p.items()
    }
