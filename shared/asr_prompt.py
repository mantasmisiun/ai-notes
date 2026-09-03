#!/usr/bin/env python3
"""A hint for the speech recogniser: a short, punctuated sentence in the
lecture's language, given to Whisper as hotwords so every window sees it.

A stock multilingual model that sees punctuated text keeps punctuating
consistently instead of drifting in and out of it. A fine-tune that emits no
punctuation, such as paprika-whisper-lt, gains nothing from one, so a model
given as a directory gets none. LECTURE_INITIAL_PROMPT overrides both."""
import os

PROMPTS = {
    "lt": "Labas vakaras. Šiandien kalbėsime apie svarbiausius dalykus: faktus, skaičius ir pavadinimus.",
    "en": "Good evening. Today we will cover the key points: the facts, the figures and the names.",
}


def initial_prompt(model, language):
    override = os.environ.get("LECTURE_INITIAL_PROMPT")
    if override is not None:
        return override.strip()
    if os.path.isdir(str(model)):
        return ""
    return PROMPTS.get(language, "")
