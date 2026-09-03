"""Prompt sets, one per note language.

The instruction language matches the output language deliberately: writing
English instructions and asking for Lithuanian output makes the model drift
between the two mid-note. The transcript language is stated separately, because
a Lithuanian lecture summarised into an English note needs the English prompt
to say where the text came from.
"""

LANG_NAMES = {"en": "English", "lt": "Lithuanian"}
LANG_NAMES_LT = {"en": "anglų", "lt": "lietuvių"}

# Section headings the summariser adds itself, per note language. The model
# writes the top of the note; the body is assembled from the section notes
# without another pass through the model, so nothing is lost to a rewrite.
HEADINGS = {
    "en": {"detail": "Detail", "open": "Open questions"},
    "lt": {"detail": "Turinys", "open": "Atviri klausimai"},
}

PROMPTS = {
    "en": {
        "section": """You are given part of a transcript of {context}, in {src}.
Time markers such as [0:03:08] show where each paragraph of the transcript
starts.

Write **detailed notes** on this part, not a summary. Someone who missed the
session should be able to follow the substance from your notes alone.

Write one short paragraph per point made, in the order the points were made.
**Begin every paragraph with the time marker of where that point starts,
copied exactly from the transcript**, for example `[0:03:08] The speaker
argues that...`. Never invent a marker: use the nearest one before the point.

Keep: definitions in the words used, numbers, names, dates, formulas, worked
examples with their steps, the reasoning behind claims, and anything flagged as
important or examinable. Attribute claims to whoever made them, the speaker,
an interviewee, a questioner, rather than stating them as fact. Where a name is
spelled several ways, use the most frequent spelling throughout.

Drop only: filler, repetition, digressions, and administrative chatter.

Do not compress for brevity. Length should follow the material. No heading, no
introduction, no conclusion, and no structure that is not in the material.

The text is machine-transcribed, so some words are wrong and there may be no
punctuation. Read through that and write about the subject matter. **Never
comment on the transcription, list misrecognised words, or discuss the quality
of the text.** If a passage is beyond understanding, skip it silently.

{prior}TRANSCRIPT PART:
{chunk}""",

        "prior": """PRECEDING CONTEXT, already covered, write nothing about it:
{prior}

""",

        "combine": """Below are detailed notes, in order, from one recording of
{context}, transcribed from {src}. The notes themselves will be placed in full
under what you write, so do not repeat or condense them.

Write in {out_lang}, in markdown, with these sections and nothing else:

## Summary
Four to six sentences on what this was about and where it ended up.

## Key concepts
Every distinct concept, term, name or claim that matters, each with a one-line
explanation in the speaker's own terms. This is a complete list, not a
selection.

## Open questions
Only questions that someone in the recording actually raised and left
unanswered, or reading they said to do. Omit this section entirely if there
were none. Do not invent questions.

Base it only on what is below. Do not invent examples or citations. Keep
technical terms in their original form where translating them would lose
meaning. Output raw markdown. Do not wrap your answer in a code fence.

DETAILED NOTES, IN ORDER:
{sections}""",

        "notes_intro": """The student also took their own notes during this session.
Treat them as more reliable than the transcript: they show what was stressed,
and they correct terms the speech recogniser will have garbled. Where the notes
and the transcript disagree on a name or a term, follow the notes.

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
        "section": """Pateikta {context} transkripcijos dalis {src_lt} kalba. Laiko
žymos, tokios kaip [0:03:08], rodo, kur prasideda kiekviena transkripcijos
pastraipa.

Parašyk **išsamias pastabas** apie šią dalį, o ne santrauką. Žmogus, kuris
nedalyvavo, turėtų iš tavo pastabų suprasti esmę.

Rašyk po vieną trumpą pastraipą kiekvienai išsakytai minčiai, ta tvarka, kuria
jos buvo išsakytos. **Kiekvieną pastraipą pradėk laiko žyma, nuo kurios ta
mintis prasideda, nukopijuota tiksliai iš transkripcijos**, pavyzdžiui
`[0:03:08] Dėstytojas teigia, kad...`. Niekada nekurk žymos pats: naudok
artimiausią prieš tą mintį esančią.

Palik: apibrėžimus tokius, kokie pasakyti, skaičius, pavadinimus, datas,
formules, išspręstus pavyzdžius su žingsniais, argumentus ir viską, kas
įvardyta kaip svarbu ar egzaminui. Teiginius priskirk tam, kas juos išsakė,
dėstytojui, pašnekovui, klausiančiajam, o ne pateik kaip faktus. Jei vardas
rašomas keliais būdais, visur naudok dažniausią.

Išmesk tik: tuščiažodžiavimą, pasikartojimus, nukrypimus ir organizacinius
dalykus.

Netrumpink dėl trumpumo. Ilgis turi atitikti medžiagą. Be antraštės, įžangos
ar išvadų.

Tekstas transkribuotas automatiškai, todėl kai kurie žodžiai neteisingi ir
skyrybos gali nebūti. Nekreipk į tai dėmesio ir rašyk apie turinį. **Niekada
nerašyk apie transkripciją, nevardyk klaidingai atpažintų žodžių ir
nekomentuok teksto kokybės.** Nesuprantamas vietas tiesiog praleisk.

{prior}TRANSKRIPCIJOS DALIS:
{chunk}""",

        "prior": """ANKSTESNIS KONTEKSTAS, jau aprašytas, apie jį nerašyk:
{prior}

""",

        "combine": """Žemiau iš eilės pateiktos išsamios vieno {context} įrašo
pastabos, transkribuotos iš {src_lt} kalbos. Pačios pastabos bus įdėtos
ištisai po tuo, ką parašysi, todėl jų nekartok ir netrumpink.

Rašyk lietuvių kalba, markdown formatu, su šiais skyriais ir nieko daugiau:

## Santrauka
Keturi–šeši sakiniai apie tai, kas buvo dėstoma ir prie ko prieita.

## Pagrindinės sąvokos
Kiekviena svarbi sąvoka, terminas, vardas ar teiginys su vienos eilutės
paaiškinimu dėstytojo terminais. Tai pilnas sąrašas, ne atranka.

## Atviri klausimai
Tik klausimai, kuriuos kas nors įraše iš tikrųjų iškėlė ir paliko neatsakytus,
arba literatūra, kurią liepė perskaityti. Jei tokių nebuvo, šio skyriaus visai
nerašyk. Nekurk klausimų pats.

Remkis tik tuo, kas pateikta žemiau. Nekurk pavyzdžių ar šaltinių. Terminus,
kurių vertimas prarastų prasmę, palik originalia forma. Rašyk gryną markdown.
Neįtrauk atsakymo į kodo bloką.

IŠSAMIOS PASTABOS IŠ EILĖS:
{sections}""",

        "notes_intro": """Studentas per šį įrašą taip pat pats užsirašė pastabų.
Laikyk jas patikimesnėmis už transkripciją: jos rodo, kas buvo pabrėžta, ir
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
