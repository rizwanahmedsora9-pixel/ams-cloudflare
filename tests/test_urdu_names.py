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
