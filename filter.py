import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["C.Created Time", "C.POS PAN Number", "utm source"]


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        logger.error(f"Missing columns: {missing}")
        raise ValueError(f"Missing columns: {missing}")

    # Only keep rows where PAN is not empty
    df = df[df["C.POS PAN Number"].notna() & (df["C.POS PAN Number"].astype(str).str.strip() != "")]
    after_pan = len(df)
    # Only keep rows where utm source is google or meta
    df = df[df["utm source"].str.lower().isin(["google", "meta"])]
    after_utm = len(df)
    logger.info(f"Rows after PAN: {after_pan}, after utm: {after_utm}")
    return df 