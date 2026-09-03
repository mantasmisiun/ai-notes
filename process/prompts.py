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

Turn this part into study notes a reader can follow without the recording.
Work topic by topic: start a new block whenever the subject changes, which is
usually every one to four minutes of speech. Every block has exactly this
shape:

### Title of the topic
[0:03:08]
- key point
- key point
One short paragraph, only where the bullets cannot carry a chain of reasoning,
a worked example or a definition that needs its context.

Rules for the blocks:
- The title names the specific content in three to eight words. Never
  "Introduction", "Discussion" or "Overview".
- The second line is the time marker where the topic starts, copied exactly
  from the transcript. Never invent one; use the nearest marker before the
  topic.
- Two to six key points, each a short phrase or one sentence. Write the content
  itself, not a narration of it: "Nasson pled guilty on 3 June 2022", never
  "The speaker says that Nasson pled guilty". Name who said something only when
  it matters who did, such as a claim by an interviewee or a lecturer's
  warning.
- Keep numbers, dates, names, definitions in the words used, formulas, worked
  steps, and anything flagged as important or examinable. Put a key term in
  **bold** the first time it appears.
- Use one spelling per name, the most frequent one in the transcript.
- Skip filler, repetition, advertising and administrative chatter. A passage
  that says nothing new gets no block.

Do not compress for brevity: every topic that was covered gets a block, and
length follows the material. Output only the blocks, no heading above them,
no introduction, no conclusion.

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

Paversk šią dalį konspektu, kurį galima sekti be įrašo. Dirbk tema po temos:
pradėk naują bloką kaskart, kai keičiasi tema, paprastai kas vieną–keturias
kalbos minutes. Kiekvienas blokas yra tiksliai tokios formos:

### Temos pavadinimas
[0:03:08]
- esminis punktas
- esminis punktas
Viena trumpa pastraipa, tik ten, kur punktai negali perteikti argumentų
grandinės, išspręsto pavyzdžio ar apibrėžimo, kuriam reikia konteksto.

Blokų taisyklės:
- Pavadinimas įvardija konkretų turinį trimis–aštuoniais žodžiais. Niekada
  „Įžanga“, „Aptarimas“ ar „Apžvalga“.
- Antra eilutė yra laiko žyma, nuo kurios tema prasideda, nukopijuota
  tiksliai iš transkripcijos. Niekada nekurk jos pats; naudok artimiausią
  prieš temą esančią.
- Nuo dviejų iki šešių punktų, kiekvienas trumpa frazė arba vienas sakinys.
  Rašyk pačią mintį, o ne jos atpasakojimą: „Nasson prisipažino kaltu 2022 m.
  birželio 3 d.“, niekada „Kalbėtojas sako, kad Nasson prisipažino“. Nurodyk,
  kas pasakė, tik kai tai svarbu, pavyzdžiui pašnekovo teiginį ar dėstytojo
  įspėjimą.
- Palik skaičius, datas, vardus, apibrėžimus tokius, kokie pasakyti, formules,
  sprendimo žingsnius ir viską, kas įvardyta kaip svarbu ar egzaminui. Esminį
  terminą pirmą kartą **paryškink**.
- Kiekvienam vardui viena rašyba, dažniausia transkripcijoje.
- Praleisk tuščiažodžiavimą, pasikartojimus, reklamą ir organizacinius
  dalykus. Ištrauka, kuri nepasako nieko naujo, bloko negauna.

Netrumpink dėl trumpumo: kiekviena aptarta tema gauna bloką, o ilgis atitinka
medžiagą. Išvesk tik blokus, be antraštės virš jų, be įžangos, be išvadų.

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
