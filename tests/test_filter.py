import pytest
import pandas as pd
from filter import apply_filters
from datetime import datetime, timedelta

today = datetime.now().date()
yesterday = today - timedelta(days=1)

def make_df(rows):
    return pd.DataFrame(rows)

def test_all_filters_pass():
    df = make_df([
        {"C.Created Time": today, "C.POS PAN Number": "123", "utm source": "google"},
        {"C.Created Time": today, "C.POS PAN Number": "456", "utm source": "meta"},
    ])
    out = apply_filters(df)
    assert len(out) == 2

def test_date_filter():
    df = make_df([
        {"C.Created Time": yesterday, "C.POS PAN Number": "123", "utm source": "google"},
        {"C.Created Time": today, "C.POS PAN Number": "456", "utm source": "meta"},
    ])
    out = apply_filters(df)
    assert len(out) == 1
    assert out.iloc[0]["C.POS PAN Number"] == "456"

def test_pan_filter():
    df = make_df([
        {"C.Created Time": today, "C.POS PAN Number": "", "utm source": "google"},
        {"C.Created Time": today, "C.POS PAN Number": " ", "utm source": "meta"},
        {"C.Created Time": today, "C.POS PAN Number": "789", "utm source": "google"},
    ])
    out = apply_filters(df)
    assert len(out) == 1
    assert out.iloc[0]["C.POS PAN Number"] == "789"

def test_utm_filter():
    df = make_df([
        {"C.Created Time": today, "C.POS PAN Number": "123", "utm source": "google"},
        {"C.Created Time": today, "C.POS PAN Number": "456", "utm source": "meta"},
        {"C.Created Time": today, "C.POS PAN Number": "789", "utm source": "other"},
    ])
    out = apply_filters(df)
    assert len(out) == 2
    assert set(out["utm source"]) == {"google", "meta"}

def test_missing_columns():
    df = pd.DataFrame({"A": [1], "B": [2]})
    with pytest.raises(ValueError):
        apply_filters(df) 