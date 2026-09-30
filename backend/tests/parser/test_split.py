from app.parser.split import split_request


def names(text):
    return [(i.drug.lower(), i.strength, i.quantity) for i in split_request(text)]


def test_brief_example():
    items = split_request("crocin and 2 ORS, dolo")
    assert [i.requested_text for i in items] == ["crocin", "2 ORS", "dolo"]
    assert names("crocin and 2 ORS, dolo") == [("crocin", None, None), ("ors", None, 2), ("dolo", None, None)]


def test_strength_and_filler():
    assert names("Hi, I need dolo 650 and pan 40 please") == [("dolo", "650", None), ("pan", "40", None)]


def test_quantities():
    assert names("2 strips of dolo 650") == [("dolo", "650", 2)]
    assert names("two crocin") == [("crocin", None, 2)]
    assert names("allegra 120 x 3") == [("allegra", "120", 3)]


def test_form_prefix_and_newlines():
    items = split_request("tab azithral 500\nsyp ascoril")
    assert [(i.drug.lower(), i.form) for i in items] == [("azithral", "tablet"), ("ascoril", "syrup")]


def test_multiword_brands_survive():
    assert names("montair lc, vicks action 500") == [
        ("montair lc", None, None),
        ("vicks action", "500", None),
    ]


def test_hindi_and_plus():
    assert names("crocin aur digene") == [("crocin", None, None), ("digene", None, None)]
    assert names("dolo + ors") == [("dolo", None, None), ("ors", None, None)]


def test_empty():
    assert split_request("  ,  and ") == []
