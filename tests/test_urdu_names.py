from app.services.urdu_names import urdu_name


def test_requested_names_and_material():
    assert urdu_name('Hamid') == 'حامد'
    assert urdu_name('FAISAL') == 'فیصل'
    assert urdu_name('DG Cement') == 'ڈی جی سیمنٹ'


def test_saved_spelling_takes_precedence_and_mixed_content_is_preserved():
    assert urdu_name('Hamid', 'حمید') == 'حمید'
    assert urdu_name('حامد 123') == 'حامد 123'
    assert urdu_name('DG Cement 50') == 'ڈی جی سیمنٹ 50'
    assert urdu_name('') == ''


def test_open_khata_style_words_are_never_spelled_out_letter_by_letter():
    """Walk-in names typed in capitals must read as words, not as "o p e n"."""
    assert urdu_name('OPEN') == 'اوپن'
    assert urdu_name('Open') == 'اوپن'
    assert urdu_name('OPEN KHATA') == 'اوپن کھاتہ'
    assert urdu_name('open khata') == 'اوپن کھاتہ'
    assert urdu_name('CASH') == 'کیش'
    assert urdu_name('PAID') == 'پیڈ'


def test_capitalised_person_names_read_as_words():
    """ALL-CAPS names with a normal vowel pattern are words, not initialisms."""
    assert urdu_name('ALI') == 'الی'
    assert urdu_name('ASIF') == 'اسیف'


def test_true_initialisms_are_still_spelled_out():
    assert urdu_name('DG') == 'ڈی جی'
    assert urdu_name('OPC') == 'او پی سی'
    assert urdu_name('GRN') == 'جی آر این'
    assert urdu_name('HBL') == 'ایچ بی ایل'
    assert urdu_name('NBP') == 'این بی پی'
