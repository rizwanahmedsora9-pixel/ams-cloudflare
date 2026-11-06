"""Best-effort Urdu rendering of names where no curated Urdu name exists.

Transliteration is inherently ambiguous; a catalogue's explicit Urdu name is
always preferable. Preserve punctuation, numbers and non-Latin text unchanged.
"""
import re

# Whole words are matched case-insensitively *before* every other rule, so a
# walk-in name typed in capitals ("OPEN", "OPEN KHATA", "CASH") is read as the
# word itself and never spelled out letter-by-letter like an initialism.
_WORDS = {
    # Walk-in / ledger vocabulary seen in client and driver names.
    'open': 'اوپن', 'khata': 'کھاتہ', 'cash': 'کیش', 'paid': 'پیڈ',
    'sale': 'سیل', 'credit': 'کریڈٹ', 'advance': 'ایڈوانس', 'rent': 'رینٹ',
    'return': 'ریٹرن', 'due': 'ڈیو', 'general': 'جنرل', 'customer': 'کسٹمر',
    'walking': 'واکنگ', 'site': 'سائٹ', 'shop': 'شاپ', 'store': 'اسٹور',
    'market': 'مارکیٹ', 'trader': 'ٹریڈر', 'traders': 'ٹریڈرز',
    'company': 'کمپنی', 'bank': 'بینک', 'account': 'اکاؤنٹ',
    'booking': 'بکنگ', 'delivery': 'ڈیلیوری', 'payment': 'پیمنٹ',
    'cement': 'سیمنٹ', 'goods': 'گڈز', 'material': 'میٹیریل',
    # Short all-caps-friendly words (single vowel), so they keep word reading.
    'work': 'ورک', 'home': 'ہوم', 'food': 'فوڈ', 'room': 'روم', 'good': 'گڈ',
    'sons': 'سنز', 'bros': 'بروز', 'mill': 'مل', 'star': 'اسٹار', 'test': 'ٹیسٹ',
    # Known names / brands.
    'hamid': 'حامد', 'hamed': 'حامد', 'faisal': 'فیصل',
    'dg': 'ڈی جی',
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

_VOWELS = set('aeiou')


def _looks_like_initialism(text: str) -> bool:
    """A short ALL-CAPS token that reads as letter names, not as a word.

    True initialisms in this trade (``DG``, ``OPC``, ``GRN``, ``HBL``, ``NBP``)
    carry at most one vowel letter.  Words people simply type in capitals --
    ``OPEN``, ``ALI``, ``ASIF`` -- keep their vowel pattern and fall through to
    the word transliterator (or the dictionary above), so the Urdu bill never
    spells them out as "o p e n".
    """
    if not (text.isupper() and 1 < len(text) <= 4):
        return False
    lowered = text.lower()
    return sum(1 for ch in lowered if ch in _VOWELS) <= 1


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
        if _looks_like_initialism(original):
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
