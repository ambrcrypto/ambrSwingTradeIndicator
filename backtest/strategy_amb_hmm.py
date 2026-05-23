"""
strategy_amb_hmm.py – AMB Dual MA Signal with HMM market-regime entry filter.

Walk-forward Hidden Markov Model classifies each trading day into one of three
regimes (Bull / Sideways / Bear).  Regime gates control which entry signals are
allowed, while all exits (MA-cross, Stop Loss) always execute.

Regime filter rules (v2 — post external review, Sideways tested and reverted):
  Bull     (+1): longEntry ✓  longReentry ✓  shortEntry ✗  shortReentry ✗
                 flipToLong ✓ (exit + entry)  flipToShort → exit-only
  Bear     (-1): longEntry ✗  longReentry ✗  shortEntry ✓  shortReentry ✓
                 flipToLong → exit-only        flipToShort ✓ (exit + entry)
  Sideways  (0): all new entries blocked; both flips → exit-only
                 (tested 2026-05-23: allowing longs in Sideways worsened all
                  metrics: Sharpe 0.220→0.100, MaxDD 11%→27%, P/L +41%→+12%)
  All regimes  : Exits (MA-cross, SL) ALWAYS execute – capital protection.

"exit-only flip": the existing position is closed (exit_long / exit_short fires
normally), but no new position is opened in the opposite direction.

Walk-forward design (no look-ahead bias):
  • Expanding window – train on bars [0 .. i-1], classify bar i.
  • Minimum training window: HMM_MIN_TRAIN = 252 bars (≈ 1 trading year).
  • Retrain every HMM_RETRAIN_EVERY = 21 bars (≈ 1 calendar month).
  • Features at bar i (20-day rolling return, 10-day rolling vol) are computed from the
    bar-close price, which is known at signal-generation time (end-of-day).
    20-day return captures trend direction; rolling vol captures regime intensity.
  • Label stability: after every retrain, hidden states are remapped by their
    mean log-return (ascending: Bear … Sideways … Bull).

Model: GaussianHMM(n_components=3, covariance_type='full'), random_state=42.

This module is intentionally self-contained.  strategy_amb.py is NOT modified.
"""

from __future__ import annotations

import warnings
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler
except ImportError as exc:
    raise ImportError(
        "hmmlearn and scikit-learn are required for the HMM regime filter.\n"
        "Install with:  pip install hmmlearn scikit-learn"
    ) from exc

from .strategy_amb import AMBParams, Trade, _calc_ma, _calc_atr, _first_day_mask


# ─────────────────────────────────────────────────────────────────────────────
# HMM hyperparameters
# ─────────────────────────────────────────────────────────────────────────────

HMM_MIN_TRAIN     = 252   # bars before first regime signal (≈ 1 trading year)
HMM_MAX_TRAIN     = 504   # rolling window cap for retrain  (≈ 2 trading years)
HMM_RETRAIN_EVERY = 21    # bars between model retrains    (≈ 1 calendar month)
HMM_VOL_WINDOW    = 10    # rolling window for volatility feature
HMM_TREND_WINDOW  = 20    # rolling window for trend/direction feature
HMM_RANDOM_STATE  = 42
HMM_N_ITER        = 100   # EM iterations per fit

_CACHE_DIR = Path(__file__).parent / "cache"

# Regime labels
BULL     =  1
SIDEWAYS =  0
BEAR     = -1

_REGIME_LABELS: dict[int, str] = {BULL: "Bull", SIDEWAYS: "Sideways", BEAR: "Bear"}
_REGIME_ORDER  = [BEAR, SIDEWAYS, BULL]   # fixed order for transition matrix


# ─────────────────────────────────────────────────────────────────────────────
# HMMResult – regime array + diagnostics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HMMResult:
    """
    Walk-forward HMM classification result aligned to the input DataFrame.

    Attributes
    ----------
    regimes
        1-D float array, same length as input df.
        Values: 1.0 = Bull, 0.0 = Sideways, -1.0 = Bear, NaN = pre-warmup.
    proba
        2-D float array, shape (n, 3): posterior probabilities per regime.
        Column order: [P(Bear), P(Sideways), P(Bull)].
        NaN rows correspond to pre-warmup bars (same mask as regimes).
    regime_pct
        Share of time in each regime over all valid (non-NaN) bars.
        Example: {'Bull': 45.2, 'Sideways': 30.1, 'Bear': 24.7}
    transition_matrix
        3 × 3 empirical transition probability matrix derived from the regime
        sequence.  Row / column order: [Bear, Sideways, Bull].
        Row i sums to 1.0 (or 0.0 if that regime never occurred).
    n_retrains
        Number of times the model was retrained.
    dates
        DatetimeIndex aligned with regimes.
    """

    regimes:           np.ndarray
    proba:             np.ndarray
    regime_pct:        dict
    transition_matrix: np.ndarray
    n_retrains:        int
    dates:             pd.DatetimeIndex

    def print_summary(self) -> None:
        """Pretty-print regime distribution and transition matrix to stdout."""
        print("\n── HMM Regime Distribution ─────────────────────────────────────")
        for label in ("Bull", "Sideways", "Bear"):
            pct = self.regime_pct.get(label, 0.0)
            bar = "█" * int(pct / 2)
            print(f"  {label:10s}: {pct:5.1f}%  {bar}")
        print(f"\n  Total retrains : {self.n_retrains}")

        print("\n── Transition Matrix (row = from → col = to) ───────────────────")
        col_labels = ["Bear", "Sideways", "Bull"]
        print("  " + "".join(f"{c:>12}" for c in col_labels))
        for i, from_lbl in enumerate(col_labels):
            row = self.transition_matrix[i]
            vals = "".join(f"{v:>12.1%}" for v in row)
            print(f"  {from_lbl:<10}{vals}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Regime filter helper
# ─────────────────────────────────────────────────────────────────────────────

def _apply_regime_filter(
    regime:        float,
    long_entry:    bool,
    long_reentry:  bool,
    short_entry:   bool,
    short_reentry: bool,
    flip_to_long:  bool,
    flip_to_short: bool,
    conf_bull:     float = np.nan,
    conf_bear:     float = np.nan,
    conf_threshold: float = 0.0,
) -> tuple[bool, bool, bool, bool, bool, bool]:
    """
    Apply HMM regime gate rules to raw signal flags.

    Returns filtered (long_entry, long_reentry, short_entry, short_reentry,
                       flip_to_long, flip_to_short).

    When regime is NaN (pre-warmup period), all signals pass through unchanged.
    "exit-only" flips are implemented by setting flip_to_X = False: the
    exit_long / exit_short condition still fires (closes the position), but no
    new entry is opened in the opposite direction.

    If conf_threshold > 0 and conf_bull/conf_bear are valid, the effective
    regime is determined by posterior probability rather than the hard label:
      P(Bull)  >= conf_threshold  → treat as Bull
      P(Bear)  >= conf_threshold  → treat as Bear (only if Bull condition not met)
      otherwise                  → treat as Sideways (block all entries)
    """
    if np.isnan(regime):
        return long_entry, long_reentry, short_entry, short_reentry, flip_to_long, flip_to_short

    # Determine effective regime
    if conf_threshold > 0.0 and not np.isnan(conf_bull) and not np.isnan(conf_bear):
        if conf_bull >= conf_threshold:
            r = BULL
        elif conf_bear >= conf_threshold:
            r = BEAR
        else:
            r = SIDEWAYS
    else:
        r = int(regime)

    if r == BULL:
        # Block short entries; flipToShort → exit-only (existing long closes, no new short)
        return long_entry, long_reentry, False, False, flip_to_long, False

    if r == BEAR:
        # Block long entries; flipToLong → exit-only (existing short closes, no new long)
        return False, False, short_entry, short_reentry, False, flip_to_short

    # SIDEWAYS: block all new entries; both flips → exit-only
    # NOTE: Allowing long entries in Sideways was tested (2026-05-23, review F1)
    # and worsened all metrics (Sharpe 0.220→0.100, MaxDD 11.28%→26.73%, P/L +41%→+12%).
    # The HMM correctly identifies difficult sideways phases — blocking here is intentional.
    return False, False, False, False, False, False


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward HMM regime classification
# ─────────────────────────────────────────────────────────────────────────────

def _hmm_cache_key(
    df: pd.DataFrame,
    min_train: int,
    max_train: int,
    retrain_every: int,
    vol_window: int,
    trend_window: int,
    n_iter: int,
    random_state: int,
) -> str:
    """SHA-256 fingerprint of data + hyper-parameters."""
    h = hashlib.sha256()
    h.update(df["close"].to_numpy(dtype=float).tobytes())
    h.update(df.index.astype("int64").to_numpy().tobytes())
    for v in (min_train, max_train, retrain_every, vol_window, trend_window, n_iter, random_state):
        h.update(v.to_bytes(4, "little"))
    return h.hexdigest()[:16]


def compute_hmm_regimes(
    df:              pd.DataFrame,
    min_train:       int = HMM_MIN_TRAIN,
    max_train:       int = HMM_MAX_TRAIN,
    retrain_every:   int = HMM_RETRAIN_EVERY,
    vol_window:      int = HMM_VOL_WINDOW,
    trend_window:    int = HMM_TREND_WINDOW,
    cache_dir:       Optional[Path] = _CACHE_DIR,
    force_recompute: bool = False,
) -> HMMResult:
    """
    Classify each bar of df into Bull / Sideways / Bear using a walk-forward
    GaussianHMM.  No look-ahead bias.

    Results are cached in *cache_dir* (keyed by data + parameter hash).
    On subsequent calls with the same data and parameters the cache is loaded
    instantly instead of re-running the expensive walk-forward loop.
    Pass force_recompute=True to bypass the cache.

    Parameters
    ----------
    df              OHLCV DataFrame with DatetimeIndex, sorted ascending.
    min_train       Minimum training bars before first regime is emitted.
    max_train       Rolling window cap: only the most recent max_train bars are
                    used for each retrain (prevents O(n^2) runtime growth).
    retrain_every   Bars between model retrains.
    vol_window      Rolling window (bars) for the volatility feature.
    trend_window    Rolling window (bars) for the trend/direction feature (sum of log-returns).
    cache_dir       Directory for caching regime arrays.  Pass None to disable.
    force_recompute If True, ignore an existing cache file and recompute.

    Returns
    -------
    HMMResult with .regimes aligned to df index.
    """    
    # ── Cache lookup ───────────────────────────────────────────────────────
    cache_file: Optional[Path] = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = _hmm_cache_key(
            df, min_train, max_train, retrain_every, vol_window,
            trend_window, HMM_N_ITER, HMM_RANDOM_STATE,
        )
        cache_file = cache_dir / f"hmm_regimes_{key}.npz"
        if cache_file.exists() and not force_recompute:
            data = np.load(cache_file, allow_pickle=True)
            if "proba" not in data.files:
                print(f"  [HMM cache outdated (no proba field) — recomputing…]")
            else:
                print(f"  [HMM cache hit: {cache_file.name}]")
                return HMMResult(
                    regimes           = data["regimes"],
                    proba             = data["proba"],
                    regime_pct        = data["regime_pct"].item(),
                    transition_matrix = data["transition_matrix"],
                    n_retrains        = int(data["n_retrains"]),
                    dates             = df.index,
                )
    close = df["close"].to_numpy(dtype=float)
    n     = len(close)

    # ── Features: 20-day rolling return (trend/direction) + 10-day rolling volatility ──
    log_ret  = np.full(n, np.nan)
    log_ret[1:] = np.log(close[1:] / close[:-1])

    # Vectorised rolling calculations (pandas) are much faster than Python loops.
    log_ret_s  = pd.Series(log_ret)
    roll_vol   = log_ret_s.rolling(window=vol_window, min_periods=vol_window).std(ddof=1).to_numpy()
    roll_trend = log_ret_s.rolling(window=HMM_TREND_WINDOW, min_periods=HMM_TREND_WINDOW).sum().to_numpy()

    # ── Walk-forward loop ──────────────────────────────────────────────────
    regimes        = np.full(n, np.nan)
    proba          = np.full((n, 3), np.nan)   # cols: [P(Bear), P(Sideways), P(Bull)]
    last_train_bar = -(retrain_every + 1)   # ensures first retrain fires at min_train
    model:     Optional[GaussianHMM]    = None
    scaler:    Optional[StandardScaler] = None
    label_map: Optional[dict]           = None
    rev_label_map: Optional[dict]       = None
    n_retrains = 0

    for i in range(min_train, n):

        # ── Retrain when interval elapsed ─────────────────────────────────
        if (i - last_train_bar) >= retrain_every:
            # Feature matrix: rolling window [max(1, i-max_train) .. i-1] → no look-ahead
            start = max(1, i - max_train)
            feats = np.column_stack([roll_trend[start:i], roll_vol[start:i]])
            valid = ~np.isnan(feats).any(axis=1)
            feats_clean = feats[valid]

            if len(feats_clean) < min_train:
                continue   # still in early ramp-up; skip this retrain attempt

            _scaler = StandardScaler()
            X       = _scaler.fit_transform(feats_clean)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _model = GaussianHMM(
                    n_components    = 3,
                    covariance_type = "full",
                    n_iter          = HMM_N_ITER,
                    random_state    = HMM_RANDOM_STATE,
                )
                _model.fit(X)

            # Remap hidden states by mean log-return: ascending → Bear … Bull
            hidden   = _model.predict(X)
            mean_ret: dict[int, float] = {}
            for s in range(3):
                mask = hidden == s
                # feats_clean[:, 0] is roll_trend → positive trend = Bull
                mean_ret[s] = float(feats_clean[mask, 0].mean()) if mask.sum() else 0.0

            sorted_states = sorted(mean_ret, key=mean_ret.__getitem__)
            _label_map = {
                sorted_states[0]: BEAR,
                sorted_states[1]: SIDEWAYS,
                sorted_states[2]: BULL,
            }

            model         = _model
            scaler        = _scaler
            label_map     = _label_map
            rev_label_map = {v: k for k, v in _label_map.items()}
            last_train_bar = i
            n_retrains    += 1

        # ── Predict regime for bar i ───────────────────────────────────────
        # log_ret[i] and roll_vol[i] are computed from bar-i close price, which
        # is fully known at signal-generation time (end-of-day).
        if model is None:
            continue
        if np.isnan(roll_trend[i]) or np.isnan(roll_vol[i]):
            continue

        feat_i = np.array([[roll_trend[i], roll_vol[i]]])
        try:
            X_i        = scaler.transform(feat_i)
            prob_i     = model.predict_proba(X_i)[0]   # shape (3,): P per raw state
            raw        = int(prob_i.argmax())
            regimes[i] = label_map[raw]
            # Map raw-state probabilities → regime columns [Bear, Sideways, Bull]
            proba[i, 0] = prob_i[rev_label_map[BEAR]]
            proba[i, 1] = prob_i[rev_label_map[SIDEWAYS]]
            proba[i, 2] = prob_i[rev_label_map[BULL]]
        except Exception:
            pass

    # ── Diagnostics ────────────────────────────────────────────────────────
    valid_r = regimes[~np.isnan(regimes)].astype(int)
    total   = len(valid_r)

    regime_pct: dict[str, float] = {}
    for val, lbl in _REGIME_LABELS.items():
        cnt = int((valid_r == val).sum())
        regime_pct[lbl] = round(cnt / total * 100.0, 1) if total else 0.0

    # Empirical transition matrix: Bear=row/col 0, Sideways=1, Bull=2
    r_to_idx = {BEAR: 0, SIDEWAYS: 1, BULL: 2}
    tm = np.zeros((3, 3))
    for j in range(len(valid_r) - 1):
        fi = r_to_idx[valid_r[j]]
        ti = r_to_idx[valid_r[j + 1]]
        tm[fi, ti] += 1.0
    row_sums = tm.sum(axis=1, keepdims=True)
    tm = np.where(row_sums > 0, tm / row_sums, 0.0)

    result = HMMResult(
        regimes           = regimes,
        proba             = proba,
        regime_pct        = regime_pct,
        transition_matrix = tm,
        n_retrains        = n_retrains,
        dates             = df.index,
    )

    # ── Save cache ────────────────────────────────────────────────────────
    if cache_file is not None:
        np.savez_compressed(
            cache_file,
            regimes           = regimes,
            proba             = proba,
            regime_pct        = np.array(regime_pct, dtype=object),
            transition_matrix = tm,
            n_retrains        = np.array(n_retrains),
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# HMM-filtered strategy runner
# ─────────────────────────────────────────────────────────────────────────────

def run_strategy_hmm(
    df:          pd.DataFrame,
    params:      AMBParams,
    hmm_result:  HMMResult,
    trade_start: "pd.Timestamp | None" = None,
    conf_threshold: float = 0.0,
) -> list[Trade]:
    """
    Run AMB strategy with HMM regime filter on OHLCV DataFrame.

    Identical to run_strategy() in strategy_amb.py, with the HMM regime gate
    inserted between flip-logic computation and final signal derivation.

    Parameters
    ----------
    df              OHLCV DataFrame, DatetimeIndex, sorted ascending.
                    Must include warmup history for MA calculation.
    params          AMBParams (same as baseline).
    hmm_result      Output of compute_hmm_regimes() computed on the same df.
    trade_start     If given, only record trades whose entry date >= trade_start.
                    State machine still warms up from bar 0.
    conf_threshold  Posterior probability threshold for regime activation.
                    0.0 (default) = use hard label (argmax of posterior).
                    >0 (e.g. 0.70) = require P(Bull/Bear) >= threshold;
                    bars below threshold are treated as Sideways (no entries).

    Returns
    -------
    list[Trade] – closed trades (open position at last bar is force-closed).
    """
    close_s = df["close"]
    close   = close_s.to_numpy(dtype=float)
    high    = df["high"].to_numpy(dtype=float)
    low_    = df["low"].to_numpy(dtype=float)
    dates   = df.index
    n       = len(df)

    regimes     = hmm_result.regimes   # aligned to df
    slow_ma     = _calc_ma(close_s, params.slow_ma_len,  params.slow_ma_type)
    fast_ma     = _calc_ma(close_s, params.fast_ma_len,  params.fast_ma_type)
    atr         = _calc_atr(high, low_, close, params.atr_sl_len)    if params.atr_sl_enable   else np.full(n, np.nan)
    atr_entry   = _calc_atr(high, low_, close, params.atr_entry_len) if params.atr_entry_enable else np.full(n, np.nan)
    signal_days = _first_day_mask(dates, params.signal_tf)

    # ── State ──────────────────────────────────────────────────────────────
    last_dir:            int   = 0
    position_open:       bool  = False
    long_above_fast_ma:  bool  = False
    short_below_fast_ma: bool  = False
    entry_price:         float = 0.0
    entry_atr:           float = 0.0
    entry_bar:           int   = 0
    entry_date:          pd.Timestamp = dates[0]

    pending_long:        bool  = False
    pending_short:       bool  = False
    pending_long_level:  float = 0.0
    pending_short_level: float = 0.0

    trades: list[Trade] = []

    for i in range(1, n):
        if np.isnan(slow_ma[i]) or np.isnan(fast_ma[i]):
            continue
        if np.isnan(slow_ma[i - 1]) or np.isnan(fast_ma[i - 1]):
            continue

        c  = close[i];  c0 = close[i - 1]
        h  = high[i]
        lo = low_[i]
        s  = slow_ma[i]; s0 = slow_ma[i - 1]
        f  = fast_ma[i]; f0 = fast_ma[i - 1]

        # ── Fast MA state tracking ─────────────────────────────────────────
        if position_open and params.use_fast_ma:
            if last_dir == 1  and c > f:
                long_above_fast_ma  = True
            if last_dir == -1 and c < f:
                short_below_fast_ma = True

        # ── Crossovers (only on signal-timeframe days) ─────────────────────
        if signal_days[i]:
            cross_above_slow = (c > s) and (c0 <= s0)
            cross_above_fast = params.use_fast_ma and (c > f) and (c0 <= f0)
            cross_below_slow = (c < s) and (c0 >= s0)
            cross_below_fast = params.use_fast_ma and (c < f) and (c0 >= f0)
        else:
            cross_above_slow = False
            cross_above_fast = False
            cross_below_slow = False
            cross_below_fast = False

        # ── SL levels ─────────────────────────────────────────────────────
        if params.atr_sl_enable and position_open and entry_price > 0 and entry_atr > 0:
            sl_long_level  = (entry_price - entry_atr * params.atr_sl_mult) if last_dir == 1  else None
            sl_short_level = (entry_price + entry_atr * params.atr_sl_mult) if last_dir == -1 else None
        elif params.sl_enable and position_open and entry_price > 0:
            sl_long_level  = (
                entry_price * (1.0 - params.sl_risk_pct / (100.0 * params.leverage_long))
                if last_dir == 1 else None
            )
            sl_short_level = (
                entry_price * (1.0 + params.sl_risk_pct / (100.0 * params.leverage_short))
                if last_dir == -1 else None
            )
        else:
            sl_long_level  = None
            sl_short_level = None

        # ── Exit conditions (NEVER filtered by regime) ─────────────────────
        exit_long_A  = position_open and last_dir == 1  and long_above_fast_ma  and cross_below_fast
        exit_long_B  = position_open and last_dir == 1  and cross_below_slow
        exit_long_SL = (sl_long_level  is not None) and (lo <= sl_long_level)
        exit_long    = exit_long_A or exit_long_B or exit_long_SL

        exit_short_A  = position_open and last_dir == -1 and short_below_fast_ma and cross_above_fast
        exit_short_B  = position_open and last_dir == -1 and cross_above_slow
        exit_short_SL = (sl_short_level is not None) and (h >= sl_short_level)
        exit_short    = exit_short_A or exit_short_B or exit_short_SL

        # ── Entry conditions ───────────────────────────────────────────────
        long_entry   = (not position_open) and (last_dir != 1)  and cross_above_slow
        long_reentry = (not position_open) and (last_dir == 1)  and cross_above_fast and (c > s)

        short_entry   = (not position_open) and (last_dir != -1) and cross_below_slow
        short_reentry = (not position_open) and (last_dir == -1) and cross_below_fast and (c < s)

        # ── ATR pending entry filter (unchanged from baseline) ─────────────
        if params.atr_entry_enable:
            ae = atr_entry[i] if not np.isnan(atr_entry[i]) else 0.0

            if (not position_open) and (last_dir != 1) and cross_above_slow and ae > 0:
                pending_long        = True
                pending_short       = False
                pending_long_level  = s + ae * params.atr_long_mult
                long_entry = False

            if (not position_open) and (last_dir != -1) and cross_below_slow and ae > 0:
                pending_short       = True
                pending_long        = False
                pending_short_level = s - ae * params.atr_short_mult
                short_entry = False

            if pending_long  and cross_below_slow:
                pending_long  = False
            if pending_short and cross_above_slow:
                pending_short = False
            if position_open:
                pending_long  = False
                pending_short = False

            if pending_long and (not position_open) and c >= pending_long_level:
                long_entry   = True
                pending_long = False

            if pending_short and (not position_open) and c <= pending_short_level:
                short_entry   = True
                pending_short = False

        # ── Flip logic (computed before regime filter so exits are unaffected)
        flip_to_short = exit_long  and cross_below_slow and params.allow_shorts
        flip_to_long  = exit_short and cross_above_slow and params.allow_longs

        # ── HMM Regime Filter ──────────────────────────────────────────────
        # Exits (exit_long, exit_short) are intentionally NOT touched here.
        # Only entry-side flags are filtered; flip_to_X = False means the
        # position closes (exit fires) but no new opposite position opens.
        (
            long_entry, long_reentry,
            short_entry, short_reentry,
            flip_to_long, flip_to_short,
        ) = _apply_regime_filter(
            regimes[i],
            long_entry, long_reentry,
            short_entry, short_reentry,
            flip_to_long, flip_to_short,
            conf_bull      = hmm_result.proba[i, 2],
            conf_bear      = hmm_result.proba[i, 0],
            conf_threshold = conf_threshold,
        )

        # ── Final signals ──────────────────────────────────────────────────
        long_signal  = ((long_entry  or long_reentry)  and params.allow_longs)  or flip_to_long
        short_signal = ((short_entry or short_reentry) and params.allow_shorts) or flip_to_short

        # ── State machine: EXIT first, then ENTRY ─────────────────────────

        if exit_long and position_open and last_dir == 1:
            if exit_long_SL:
                if params.atr_sl_enable:
                    pct = ((sl_long_level - entry_price) / entry_price * 100.0) * params.leverage_long
                else:
                    pct = -params.sl_risk_pct
            else:
                pct = ((c - entry_price) / entry_price * 100.0) * params.leverage_long
            if trade_start is None or entry_date >= trade_start:
                trades.append(Trade(
                    entry_bar=entry_bar, entry_date=entry_date,
                    entry_price=entry_price, direction=1,
                    exit_bar=i, exit_date=dates[i],
                    exit_price=c,
                    exit_type="SL" if exit_long_SL else "CL",
                    pct=pct,
                ))
            position_open       = False
            long_above_fast_ma  = False
            short_below_fast_ma = False
            entry_price         = 0.0

        elif exit_short and position_open and last_dir == -1:
            if exit_short_SL:
                if params.atr_sl_enable:
                    pct = ((entry_price - sl_short_level) / entry_price * 100.0) * params.leverage_short
                else:
                    pct = -params.sl_risk_pct
            else:
                pct = ((entry_price - c) / entry_price * 100.0) * params.leverage_short
            if trade_start is None or entry_date >= trade_start:
                trades.append(Trade(
                    entry_bar=entry_bar, entry_date=entry_date,
                    entry_price=entry_price, direction=-1,
                    exit_bar=i, exit_date=dates[i],
                    exit_price=c,
                    exit_type="SL" if exit_short_SL else "CS",
                    pct=pct,
                ))
            position_open       = False
            long_above_fast_ma  = False
            short_below_fast_ma = False
            entry_price         = 0.0

        # ── Open new position ──────────────────────────────────────────────
        if long_signal:
            last_dir            = 1
            position_open       = True
            entry_price         = c
            entry_atr           = float(atr[i]) if not np.isnan(atr[i]) else 0.0
            entry_bar           = i
            entry_date          = dates[i]
            long_above_fast_ma  = c > f
            short_below_fast_ma = False
            pending_long        = False
            pending_short       = False

        elif short_signal:
            last_dir            = -1
            position_open       = True
            entry_price         = c
            entry_atr           = float(atr[i]) if not np.isnan(atr[i]) else 0.0
            entry_bar           = i
            entry_date          = dates[i]
            short_below_fast_ma = c < f
            long_above_fast_ma  = False
            pending_long        = False
            pending_short       = False

    # ── Close open position at last bar (unrealized → realized) ───────────
    if position_open and entry_price > 0 and (trade_start is None or entry_date >= trade_start):
        c = close[-1]
        if last_dir == 1:
            pct   = ((c - entry_price) / entry_price * 100.0) * params.leverage_long
            etype = "CL_OPEN"
        else:
            pct   = ((entry_price - c) / entry_price * 100.0) * params.leverage_short
            etype = "CS_OPEN"
        trades.append(Trade(
            entry_bar=entry_bar, entry_date=entry_date,
            entry_price=entry_price, direction=last_dir,
            exit_bar=n - 1, exit_date=dates[-1],
            exit_price=c,
            exit_type=etype,
            pct=pct,
        ))

    return trades
