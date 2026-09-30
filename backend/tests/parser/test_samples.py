import io

import pytest
from PIL import Image

from app import parser


def test_list_samples():
    samples = parser.list_samples()
    assert len(samples) == 3
    for s in samples:
        assert s.thumbnail_url == f"/api/samples/{s.sample_id}/image"
        assert s.label


def test_load_every_sample():
    for s in parser.list_samples():
        image, mime, parsed = parser.load_sample(s.sample_id)
        assert mime == "image/jpeg"
        Image.open(io.BytesIO(image)).verify()
        assert parsed.lines
        assert all(line.drug for line in parsed.lines)


def test_unknown_sample():
    with pytest.raises(KeyError):
        parser.load_sample("nope")
