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
        "section": """You are given part of a transcript of {context}, in {src}.
It came from speech recognition, so expect disfluencies and occasional wrong
words.

Write **detailed notes** on this part, not a summary. Someone who missed the
session should be able to follow the substance from your notes alone.

Keep: definitions in the words used, numbers, names, dates, formulas, worked
examples with their steps, the reasoning behind claims, and anything flagged as
important or examinable. Keep the order things were said in.

Drop only: filler, repetition, digressions, and administrative chatter.

Do not compress for brevity. Length should follow the material. If a passage is
too garbled to interpret, ignore it rather than guessing. Do not add an
introduction or a conclusion, and do not invent structure that is not there.

TRANSCRIPT PART:
{chunk}""",

        "combine": """Below are sequential detailed notes from one recording of
{context}, transcribed from {src}. They are in order.

**Your job is to organise them, not to shorten them.** Merge the parts into one
coherent note, remove duplication where the same point appears twice across a
boundary, and impose the structure below. Preserve the specifics: every
definition, number, name, formula and worked example that appears in the input
must appear in your output.

A reader should not be able to tell the note was assembled from parts.

Write in {out_lang}, in markdown, with these sections and nothing else:

## Summary
Four to six sentences on what this was about and where it ended up.

## Key concepts
Each concept with a one-line explanation in the speaker's own terms.

## Detail
The substance, in the order it was covered, as prose with subheadings. This is
the body of the note and should carry almost everything from the input.

## Open questions
Anything left unresolved, or flagged as needing further reading. Omit the
section if there was nothing.

Base it only on what is below. Do not invent examples or citations. Keep
technical terms in their original form where translating them would lose
meaning. Output raw markdown. Do not wrap your answer in a code fence.

DETAILED NOTES, IN ORDER:
{sections}""",

        "notes_intro": """The student also took their own notes during this lecture.
Treat them as more reliable than the transcript: they show what the lecturer
stressed, and they correct terms the speech recogniser will have garbled. Where
the notes and the transcript disagree on a name or a term, follow the notes.

STUDENT'S OWN NOTES:
{notes}

""",
        "notes_heading": "Your notes",

        "topic": """Below is a summary of {context}.

Reply with a short title for it: three to seven words, naming the specific
subject matter. No quotes, no punctuation at the end, no prefix such as
"Lecture on". Reply with the title and nothing else.

{note}""",
    },

    "lt": {
        "section": """Pateikta {context} transkripcijos dalis {src_lt} kalba.
Ji gauta iš kalbos atpažinimo sistemos, todėl pasitaiko nesklandumų ir
klaidingai atpažintų žodžių.

Parašyk **išsamias pastabas** apie šią dalį, o ne santrauką. Žmogus, kuris
nedalyvavo, turėtų iš tavo pastabų suprasti esmę.

Palik: apibrėžimus tokius, kokie pasakyti, skaičius, pavadinimus, datas,
formules, išspręstus pavyzdžius su žingsniais, argumentus ir viską, kas
įvardyta kaip svarbu ar egzaminui. Išlaikyk pasakojimo eiliškumą.

Išmesk tik: tuščiažodžiavimą, pasikartojimus, nukrypimus ir organizacinius
dalykus.

Netrumpink dėl trumpumo. Ilgis turi atitikti medžiagą. Jei kuri nors vieta per
daug iškraipyta, praleisk ją, o ne spėk. Nerašyk įžangos ar išvadų.

TRANSKRIPCIJOS DALIS:
{chunk}""",

        "combine": """Žemiau iš eilės pateiktos išsamios vieno {context} įrašo
pastabos. Jos eina ta pačia tvarka. Įrašas transkribuotas iš {src_lt} kalbos.

**Tavo užduotis jas sutvarkyti, o ne sutrumpinti.** Sujunk dalis į vientisą
konspektą, pašalink pasikartojimus ties dalių sandūromis ir suskirstyk pagal
žemiau nurodytą struktūrą. Išlaikyk konkretybes: kiekvienas apibrėžimas,
skaičius, pavadinimas, formulė ir išspręstas pavyzdys turi likti.

Skaitytojas neturėtų pastebėti, kad konspektas sudėtas iš dalių.

Rašyk lietuvių kalba, markdown formatu, su šiais skyriais ir nieko daugiau:

## Santrauka
Keturi–šeši sakiniai apie tai, kas buvo dėstoma ir prie ko prieita.

## Pagrindinės sąvokos
Kiekviena sąvoka su vienos eilutės paaiškinimu dėstytojo terminais.

## Turinys
Esmė ta pačia tvarka, kuria buvo dėstoma, ištisiniu tekstu su paantraštėmis.
Tai yra konspekto pagrindas ir jame turi likti beveik viskas.

## Atviri klausimai
Kas liko neatsakyta arba paminėta kaip reikalaujantis papildomo skaitymo.
Praleisk šį skyrių, jei tokių dalykų nebuvo.

Remkis tik tuo, kas pateikta žemiau. Nekurk pavyzdžių ar šaltinių. Terminus,
kurių vertimas prarastų prasmę, palik originalia forma. Rašyk gryną markdown.
Neįtrauk atsakymo į kodo bloką.

IŠSAMIOS PASTABOS IŠ EILĖS:
{sections}""",

        "notes_intro": """Studentas per šią paskaitą taip pat pats užsirašė pastabų.
Laikyk jas patikimesnėmis už transkripciją: jos rodo, ką dėstytojas pabrėžė, ir
pataiso terminus, kuriuos kalbos atpažinimo sistema iškraipė. Kai pastabos ir
transkripcija nesutaria dėl pavadinimo ar termino, remkis pastabomis.

STUDENTO PASTABOS:
{notes}

""",
        "notes_heading": "Jūsų pastabos",

        "topic": """Žemiau pateikta {context} santrauka.

Atsakyk trumpu pavadinimu: nuo trijų iki septynių žodžių, įvardijančių konkrečią
temą. Be kabučių, be skyrybos ženklo pabaigoje, be priešdėlio „Paskaita apie".
Atsakyk tik pavadinimu ir nieko daugiau.

{note}""",
    },
}


def describe(area="", subject="", kind="", lang="en"):
    """A phrase naming what this recording actually is, so the model does not
    treat a job interview or a game review as a university lecture."""
    if lang == "lt":
        if kind and subject:
            return f"įrašo: {kind} tema „{subject}“"
        if subject:
            return f"įrašo tema „{subject}“"
        return "įrašo"
    if kind and subject:
        art = "an" if kind[:1].lower() in "aeiou" else "a"
        return f"{art} {kind.lower()} session on {subject}" + (f", in {area}" if area else "")
    if subject:
        return f"a session on {subject}" + (f", in {area}" if area else "")
    return "a recorded session"


def get(note_lang, src_lang, context="a recorded session"):
    """Prompt set for the note language, with the transcript language filled in.
    Falls back to English for any language without a translated set."""
    p = PROMPTS.get(note_lang, PROMPTS["en"])
    return {
        k: v.replace("{out_lang}", LANG_NAMES.get(note_lang, note_lang))
            .replace("{context}", context)
            .replace("{src_lt}", LANG_NAMES_LT.get(src_lang, src_lang))
            .replace("{src}", LANG_NAMES.get(src_lang, src_lang))
        for k, v in p.items()
    }
