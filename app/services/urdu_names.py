"""Best-effort Urdu rendering of names where no curated Urdu name exists.

Transliteration is inherently ambiguous; a catalogue's explicit Urdu name is
always preferable. Preserve punctuation, numbers and non-Latin text unchanged.
"""
import re

_WORDS = {
    'hamid': 'حامد', 'hamed': 'حامد', 'faisal': 'فیصل',
    'cement': 'سیمنٹ', 'dg': 'ڈی جی',
}
_LETTERS = {
    'a': 'ا', 'b': 'ب', 'c': 'ک', 'd': 'د', 'e': 'ی', 'f': 'ف',
    'g': 'گ', 'h': 'ہ', 'i': 'ی', 'j': 'ج', 'k': 'ک', 'l': 'ل',
    'm': 'م', 'n': 'ن', 'o': 'و', 'p': 'پ', 'q': 'ق', 'r': 'ر',
    's': 'س', 't': 'ت', 'u': 'و', 'v': 'و', 'w': 'و', 'x': 'کس',
    'y': 'ی', 'z': 'ز',
}
_PAIRS = {'sh': 'ش', 'ch': 'چ', 'kh': 'خ', 'gh': 'غ', 'ph': 'ف',
          'th': 'تھ', 'dh': 'دھ', 'bh': 'بھ', 'aa': 'ا', 'ee': 'ی',
          'oo': 'و', 'ai': 'ی', 'ay': 'ے', 'ou': 'او'}


def urdu_name(name, preferred=None):
    """Use a saved spelling first; otherwise transliterate Latin words locally."""
    preferred = str(preferred or '').strip()
    if preferred:
        return preferred
    name = str(name or '').strip()

    def word(match):
        original = match.group()
        text = original.lower()
        if text in _WORDS:
            return _WORDS[text]
        # Initialisms are read as letter names rather than a single word.
        if original.isupper() and 1 < len(original) <= 4:
            letters = {'a': 'اے', 'b': 'بی', 'c': 'سی', 'd': 'ڈی', 'e': 'ای',
                       'f': 'ایف', 'g': 'جی', 'h': 'ایچ', 'i': 'آئی', 'j': 'جے',
                       'k': 'کے', 'l': 'ایل', 'm': 'ایم', 'n': 'این', 'o': 'او',
                       'p': 'پی', 'q': 'کیو', 'r': 'آر', 's': 'ایس', 't': 'ٹی',
                       'u': 'یو', 'v': 'وی', 'w': 'ڈبلیو', 'x': 'ایکس',
                       'y': 'وائی', 'z': 'زی'}
            return ' '.join(letters[c] for c in text)
        result = []
        i = 0
        while i < len(text):
            pair = text[i:i + 2]
            if pair in _PAIRS:
                result.append(_PAIRS[pair])
                i += 2
            else:
                # Short internal vowels are typically unwritten in Urdu.
                if text[i] not in 'ae' or i == 0 or i == len(text) - 1:
                    result.append(_LETTERS[text[i]])
                i += 1
        return ''.join(result)

    return re.sub(r'[A-Za-z]+', word, name)
