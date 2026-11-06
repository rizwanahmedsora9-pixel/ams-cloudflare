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


def test_titles_and_honorifics():
    """چوہدری مرزا صاحب -- "CH. MIRZA SB" must read the way clients say it.

    ``SB`` is the local written short form of صاحب and ``CH.`` of چوہدری;
    both expand to the full Urdu honorific instead of being spelled out.
    """
    assert urdu_name('CH.') == 'چوہدری.'
    assert urdu_name('CHAUDHRY') == 'چوہدری'
    assert urdu_name('CH MIRZA SB') == 'چوہدری مرزا صاحب'
    assert urdu_name('CH. ALI SB') == 'چوہدری. علی صاحب'
    assert urdu_name('MIRZA SAHIB') == 'مرزا صاحب'
    assert urdu_name('MALIK KHAN') == 'ملک خان'
    assert urdu_name('SB') == 'صاحب'


def test_gujrat_places_and_villages():
    """District towns and villages keep their real Urdu spellings."""
    assert urdu_name('GUJRAT') == 'گجرات'
    assert urdu_name('KHARIAN') == 'کھاریاں'
    assert urdu_name('LALAMUSA') == 'لالہ موسیٰ'
    assert urdu_name('LALA MUSA') == 'لالہ موسیٰ'
    assert urdu_name('JALALPUR JATTAN') == 'جلالپور جٹاں'
    assert urdu_name('SARAI ALAMGIR') == 'سرائے عالم گیر'
    assert urdu_name('JALAL PUR SOBTIAN') == 'جلال پور سوہتیاں'
    assert urdu_name('DINGA') == 'ڈنگہ'
    assert urdu_name('KUNJAH') == 'کنجاہ'
    assert urdu_name('TANDA') == 'ٹنڈہ'
    assert urdu_name('BHAGWAL') == 'بھگوال'


def test_common_boys_names():
    assert urdu_name('ASIF') == 'آصف'
    assert urdu_name('ALI') == 'علی'
    assert urdu_name('USMAN') == 'عثمان'
    assert urdu_name('IMRAN') == 'عمران'
    assert urdu_name('BILAL') == 'بلال'
    assert urdu_name('HAMZA') == 'حمزہ'
    assert urdu_name('HASSAN') == 'حسن'
    assert urdu_name('HUSSAIN') == 'حسین'
    assert urdu_name('YOUNIS') == 'یونس'
    assert urdu_name('TEST DRIVER') == 'ٹیسٹ ڈریور'


def test_gujrat_clans():
    assert urdu_name('WARRAICH') == 'وڑائچ'
    assert urdu_name('GONDAL') == 'گوندل'
    assert urdu_name('TARAR') == 'ترار'
    assert urdu_name('CHEEMA') == 'چیمہ'
    assert urdu_name('GUJJAR') == 'گجر'


def test_true_initialisms_are_still_spelled_out():
    assert urdu_name('DG') == 'ڈی جی'
    assert urdu_name('OPC') == 'او پی سی'
    assert urdu_name('GRN') == 'جی آر این'
    assert urdu_name('HBL') == 'ایچ بی ایل'
    assert urdu_name('NBP') == 'این بی پی'
