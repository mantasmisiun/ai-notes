"""Prompt sets, one per note language.

The instruction language matches the output language deliberately: writing
English instructions and asking for Lithuanian output makes the model drift
between the two mid-note. The transcript language is stated separately, because
a Lithuanian lecture summarised into an English note needs the English prompt
to say where the text came from.
"""

import re

LANG_NAMES = {"en": "English", "lt": "Lithuanian"}
LANG_NAMES_LT = {"en": "anglų", "lt": "lietuvių"}

# Section headings the summariser adds itself, per note language. The model
# writes the top of the note; the body is assembled from the section notes
# without another pass through the model, so nothing is lost to a rewrite.
HEADINGS = {
    "en": {"detail": "Detail", "open": "Follow-ups", "legacy_open": "Open questions"},
    "lt": {"detail": "Turinys", "open": "Tolesni darbai", "legacy_open": "Atviri klausimai"},
}

# A Follow-ups section is asked for only when the material contains something
# that looks like one. Three models in a row, told to omit the section when
# there was nothing, invented questions rather than leave it out.
# Whole words: a bare substring "exam" matched "have you examined this
# critically" and a video about a church got a Follow-ups section.
FOLLOWUP_TRIGGERS = {
    "en": re.compile(r"\b(?:homework|assignments?|reading list|read (?:the )?chapter|"
                     r"textbook|for next week|next (?:lecture|seminar|class)|look (?:it )?up|"
                     r"hand (?:it )?in|due (?:date|on|by)|prepare for|before next|exams?)\b", re.I),
    "lt": re.compile(r"\b(?:namų darb\w*|užduot\w*|perskaityk\w*|perskaityt\w*|skaityk\w*|"
                     r"vadovėl\w*|kit[aąi]\w* paskait\w*|kit[aąi]\w* savait\w*|atsiskait\w*|"
                     r"pasiruoš\w*|egzamin\w*|iki kito)\b", re.I),
}

LECTURE_KINDS = ("lecture", "seminar", "lab", "tutorial", "workshop", "class", "lesson",
                 "paskait", "seminar", "pratyb", "laborator", "pamok", "užsiėm")


def roles(kind, lang="en"):
    """Who is called what. One name per role throughout, so 'a participant'
    cannot stand for the presenter in one block and a bystander in the next."""
    lecture = any(w in (kind or "").lower() for w in LECTURE_KINDS)
    if lang == "lt":
        if lecture:
            return ("Dėstytoją vadink „dėstytoju“, klausiančius studentus „studentu“. "
                    "Tas pats žmogus visame konspekte vadinamas tuo pačiu vardu.")
        return ("Įrašą darantį žmogų vadink „vedėju“, visus kitus pagal vaidmenį, kuris "
                "nesikeičia: „pašnekovas“, „narys“, „buvęs narys“. Niekada „dalyvis“ "
                "dviem skirtingiems žmonėms.")
    if lecture:
        return ("Call the lecturer \"the lecturer\" and anyone asking a question \"a "
                "student\". The same person is called the same thing throughout.")
    return ("Call the person who made the recording \"the presenter\" and everyone "
            "else by a role that stays the same throughout: \"an interviewee\", \"a "
            "member\", \"a former member\". Never \"a participant\" for two different "
            "people.")


def wants_followups(text, lang="en"):
    t = text or ""
    for key in {lang, "en"}:
        rx = FOLLOWUP_TRIGGERS.get(key)
        if rx and rx.search(t):
            return True
    return False

PROMPTS = {
    "en": {
        "section": """You are given part of a transcript of {context}, in {src}.
Time markers such as [0:03:08] show where each paragraph of the transcript
starts.

Turn this part into study notes a reader can follow without the recording.
Work topic by topic: one block per distinct subject, however briefly it was
covered. A subject that got two sentences gets a block with one or two
points; a news bulletin or a quick run through several items gets a block
per item. Every block has exactly this shape:

### Title of the topic
[0:03:08]
- key point
- key point
One short paragraph, only where the bullets cannot carry a chain of reasoning,
a worked example or a definition that needs its context.

Rules for the blocks:
- The title names the specific content in three to eight words, in sentence
  case: a capital only on the first word and on proper names. Never
  "Introduction", "Discussion" or "Overview". If the speaker returns to a
  topic that already has a block, use exactly the same title again: blocks
  with the same title are joined, each part keeping its own time marker.
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
- {roles}
- Use one spelling per name: the spelling in the list of names below if it is
  there, otherwise the most frequent one in the transcript.
- Skip filler, repetition, advertising and administrative chatter. A passage
  that says nothing new gets no block.

Do not compress for brevity: every topic that was covered gets a block, and
length follows the material. Output only the blocks, no heading above them,
no introduction, no conclusion.

The text is machine-transcribed, so some words are wrong and there may be no
punctuation. Read through that and write about the subject matter. **Never
comment on the transcription, list misrecognised words, or discuss the quality
of the text.** A word that is not an English word is a recognition error:
leave it out, never explain it or guess a meaning for it. If a passage is
beyond understanding, skip it silently.

{names}{prior}TRANSCRIPT PART:
{chunk}""",

        "prior": """PRECEDING CONTEXT, already covered, write nothing about it:
{prior}

""",

        "names": """NAMES ALREADY IN USE, keep these spellings exactly:
{names}

""",

        "followups": """## Follow-ups
Only things someone in the recording explicitly told the listener to read,
look up, prepare or hand in, each quoted or closely paraphrased. Nothing else
belongs here.

""",

        "combine": """Below are detailed notes, in order, from one recording of
{context}, transcribed from {src}. The notes themselves will be placed in full
under what you write, so do not repeat or condense them.

Write in {out_lang}, in markdown, with these sections and nothing else:

## Summary
Four to six sentences on what this was about and where it ended up.

## Key concepts
Five to ten entries: only the terms, names and claims specific to this
recording that a reader would need explained, each with a one-line
explanation in the speaker's own terms. Never an everyday word with a
dictionary definition, never a place or a date, never an entry twice.

{followups}Base it only on what is below. Do not invent examples or citations. Keep
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
        "notes_heading": "My notes",

        "material_intro": """Course material the student linked for this session: slides, a
handout, a syllabus. Treat it as the authority on names, terms and formulas,
above the transcript. Use it to get those right and to follow the lecturer's
structure; do not summarise the material itself, only what was said.

COURSE MATERIAL:
{material}

""",

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
po vieną bloką kiekvienai atskirai temai, kad ir kaip trumpai ji buvo
paliesta. Tema, kuriai teko du sakiniai, gauna bloką su vienu ar dviem
punktais; žinių apžvalga ar greitas kelių dalykų išvardijimas gauna po bloką
kiekvienam. Kiekvienas blokas yra tiksliai tokios formos:

### Temos pavadinimas
[0:03:08]
- esminis punktas
- esminis punktas
Viena trumpa pastraipa, tik ten, kur punktai negali perteikti argumentų
grandinės, išspręsto pavyzdžio ar apibrėžimo, kuriam reikia konteksto.

Blokų taisyklės:
- Pavadinimas įvardija konkretų turinį trimis–aštuoniais žodžiais, rašomas
  kaip sakinys: didžioji raidė tik pirmame žodyje ir tikriniuose varduose.
  Niekada „Įžanga“, „Aptarimas“ ar „Apžvalga“. Jei kalbėtojas grįžta prie temos, kuri
  jau turi bloką, naudok tiksliai tą patį pavadinimą: vienodai pavadinti blokai
  sujungiami, kiekviena dalis išlaiko savo laiko žymą.
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
- {roles}
- Kiekvienam vardui viena rašyba: ta, kuri yra žemiau pateiktame vardų sąraše,
  o jei jos ten nėra, dažniausia transkripcijoje.
- Praleisk tuščiažodžiavimą, pasikartojimus, reklamą ir organizacinius
  dalykus. Ištrauka, kuri nepasako nieko naujo, bloko negauna.

Netrumpink dėl trumpumo: kiekviena aptarta tema gauna bloką, o ilgis atitinka
medžiagą. Išvesk tik blokus, be antraštės virš jų, be įžangos, be išvadų.

Tekstas transkribuotas automatiškai, todėl kai kurie žodžiai neteisingi ir
skyrybos gali nebūti. Nekreipk į tai dėmesio ir rašyk apie turinį. **Niekada
nerašyk apie transkripciją, nevardyk klaidingai atpažintų žodžių ir
nekomentuok teksto kokybės.** Žodis, kurio lietuvių kalboje nėra, yra
atpažinimo klaida: praleisk jį, niekada jo neaiškink ir nespėliok reikšmės.
Nesuprantamas vietas tiesiog praleisk.

{names}{prior}TRANSKRIPCIJOS DALIS:
{chunk}""",

        "prior": """ANKSTESNIS KONTEKSTAS, jau aprašytas, apie jį nerašyk:
{prior}

""",

        "names": """JAU NAUDOJAMI VARDAI, išlaikyk tiksliai šias rašybas:
{names}

""",

        "followups": """## Tolesni darbai
Tik tai, ką kas nors įraše aiškiai liepė perskaityti, susirasti, pasiruošti ar
atsiskaityti, kiekvienas punktas pacituotas arba artimai perpasakotas. Niekas
kita čia nepriklauso.

""",

        "combine": """Žemiau iš eilės pateiktos išsamios vieno {context} įrašo
pastabos, transkribuotos iš {src_lt} kalbos. Pačios pastabos bus įdėtos
ištisai po tuo, ką parašysi, todėl jų nekartok ir netrumpink.

Rašyk lietuvių kalba, markdown formatu, su šiais skyriais ir nieko daugiau:

## Santrauka
Keturi–šeši sakiniai apie tai, apie ką buvo kalbama ir prie ko prieita.

## Pagrindinės sąvokos
Nuo penkių iki dešimties įrašų: tik šiam įrašui būdingi terminai, vardai ir
teiginiai, kuriuos skaitytojui reikėtų paaiškinti, kiekvienas su vienos
eilutės paaiškinimu kalbėtojo žodžiais. Niekada kasdienis žodis su žodyno
apibrėžimu, niekada vietovė ar data, niekada tas pats įrašas du kartus.

{followups}Remkis tik tuo, kas pateikta žemiau. Nekurk pavyzdžių ar šaltinių. Terminus,
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
        "notes_heading": "Mano pastabos",

        "material_intro": """Studento susieta šio užsiėmimo medžiaga: skaidrės, dalijamoji
medžiaga, programa. Laikyk ją patikimesne už transkripciją vardams, terminams
ir formulėms. Naudok ją jiems tiksliai užrašyti ir dėstytojo struktūrai sekti;
pačios medžiagos neatpasakok, tik tai, kas buvo pasakyta.

MEDŽIAGA:
{material}

""",

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
    # A Type without a Subject still says what the recording is. It used to
    # be dropped, so "LRT Panorama" was summarised as "a recording".
    if lang == "lt":
        if kind and subject:
            return f"įrašo: {kind} tema „{subject}“"
        if subject:
            return f"įrašo tema „{subject}“"
        if kind:
            return f"įrašo ({kind})"
        return "įrašo"
    if kind and subject:
        art = "an" if kind[:1].lower() in "aeiou" else "a"
        return f"{art} {kind.lower()} session on {subject}" + (f", in {area}" if area else "")
    if subject:
        return f"a session on {subject}" + (f", in {area}" if area else "")
    if kind:
        return f"a recording ({kind})"
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
