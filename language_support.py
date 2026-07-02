"""
Language detection and translation support for multi-language conversations.
Supports: English, Hindi, Marathi, and Hinglish.
"""

import re
from typing import Optional

# Supported languages
SUPPORTED_LANGS = {
    'en': 'English',
    'hi': 'Hindi',
    'mr': 'Marathi',
    'hinglish': 'Hinglish'
}

# Language detection markers - expanded for better accuracy
HINDI_MARKERS = {"मैं", "मुझे", "क्या", "नहीं", "हूँ", "हूं", "कैसे", "कृपया", "बहुत", "दुख", "चिंता", "तनाव", "अकेला", "डर", "मेरा", "तुम", "आप", "हम"}
MARATHI_MARKERS = {"मला", "काय", "नाही", "आहे", "कसं", "कशी", "खूप", "झाली", "करू", "पाहिजे", "तणाव", "एकटा", "भीती", "तुला", "माझं", "तुझं"}

# Hinglish markers (common in Romanized Hindi/Marathi)
HINGLISH_MARKERS = {'ky', 'kya', 'nahi', 'hai', 'hoon', 'mujhe', 'aap', 'hum', 'tum', 'mein', 'kyu', 'bohot', 'bahut', 'hota', 'hoti', 'tha', 'thi'}


def detect_language(text: str) -> str:
    """
    Detect the language of input text.
    Returns: 'en', 'hi', 'mr', or 'hinglish'
    """
    if not text or not text.strip():
        return 'en'

    text_lower = text.lower().strip()

    # Check for Devanagari script
    if re.search(r"[\u0900-\u097F]", text):
        devanagari_text = text
        hindi_hits = sum(1 for token in HINDI_MARKERS if token in devanagari_text)
        marathi_hits = sum(1 for token in MARATHI_MARKERS if token in devanagari_text)
        
        # If Marathi markers are significantly more, it's Marathi
        if marathi_hits >= 2 and marathi_hits > hindi_hits:
            return 'mr'
        return 'hi'

    # Check for Romanized text
    tokens = set(re.findall(r"[a-z]+", text_lower))
    
    # Check for Marathi-specific Romanized words
    marathi_roman = {'mla', 'mala', 'bhuk', 'lagli', 'ahe', 'kru', 'karu', 'kay', 'zala', 'zhala', 'tula', 'majha', 'tujha'}
    marathi_hits = len(tokens & marathi_roman)
    
    if marathi_hits >= 2:
        return 'mr'
    
    # Check for Hinglish/Hindi Romanized
    hinglish_hits = len(tokens & HINGLISH_MARKERS)
    if hinglish_hits >= 2:
        return 'hinglish'
    
    return 'en'


def translate_to_english(text: str, source_lang: str) -> str:
    """
    Translate text from source language to English for processing.
    Uses the main LLM for translation.
    """
    if source_lang == 'en' or not text or not text.strip():
        return text
    
    try:
        from llm import llm
        from langchain_core.messages import HumanMessage
        
        lang_name = SUPPORTED_LANGS.get(source_lang, 'Unknown')
        prompt = f"""Translate the following {lang_name} text to English.
Only provide the English translation, nothing else.

Text: {text}"""
        
        response = llm.invoke([HumanMessage(content=prompt)])
        translation = response.content.strip()
        return translation if translation else text
        
    except Exception as e:
        print(f"Translation error: {e}")
        return text


def translate_from_english(text: str, target_lang: str) -> str:
    """
    Translate English text to target language for response.
    Uses the main LLM for translation.
    """
    if target_lang == 'en' or not text or not text.strip():
        return text
    
    try:
        from llm import llm
        from langchain_core.messages import HumanMessage
        
        lang_name = SUPPORTED_LANGS.get(target_lang, 'Unknown')
        
        if target_lang == 'hinglish':
            lang_instruction = """Respond in natural Romanized Hinglish using Latin characters. 
Use casual, conversational Hindi mixed with English words. Keep it warm and simple."""
        elif target_lang == 'mr':
            lang_instruction = "Respond in Marathi. Keep it warm, simple, and conversational."
        else:
            lang_instruction = f"Respond in {lang_name}."
        
        prompt = f"""Translate the following English text to {lang_name}.
{lang_instruction}
Only provide the translation, nothing else.

English text: {text}"""
        
        response = llm.invoke([HumanMessage(content=prompt)])
        translation = response.content.strip()
        return translation if translation else text
        
    except Exception as e:
        print(f"Translation error: {e}")
        return text


def get_language_name(lang_code: str) -> str:
    """Get human-readable language name."""
    return SUPPORTED_LANGS.get(lang_code, 'Unknown')