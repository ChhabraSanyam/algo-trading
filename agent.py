import os, time, requests, numpy as np

API_URL = os.getenv("API_URL", "http://SERVER_IP:8001")
API_KEY = os.getenv("TEAM_API_KEY", "YOUR_KEY_HERE")
HEADERS = {"X-API-Key": API_KEY}

POS_PCT = 1.00
STOP = 0.20  # hard stop from entry (20%)
TRAIL_ARM = 0.08
TRAIL_GIVEBACK = 0.04

RANGE_WIN = 10
EVENT_MOVE_PCT = 0.08
PANIC_UP_RET = 0.20
PANIC_DEFAULT_RET = 0.25
PANIC_3BAR_RET = 0.30

def get_price():
    return requests.get(f"{API_URL}/api/price", headers=HEADERS, timeout=5).json()

def get_portfolio():
    return requests.get(f"{API_URL}/api/portfolio", headers=HEADERS, timeout=5).json()

def buy(qty):
    return requests.post(f"{API_URL}/api/buy", json={"quantity": qty}, headers=HEADERS, timeout=5).json()

def sell(qty):
    return requests.post(f"{API_URL}/api/sell", json={"quantity": qty}, headers=HEADERS, timeout=5).json()

def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def infer_entry_price(port, fallback_price):
    for key in ("avg_entry_price", "average_price", "avg_price", "entry_price", "avg_cost"):
        v = port.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return float(fallback_price)

def decide(hist, port, price, state):
    min_needed = max(RANGE_WIN + 2, 8)
    if len(hist) < min_needed:
        return "hold", 0

    p = np.asarray(hist, dtype=float)
    ret1 = p[-1] / p[-2] - 1.0
    ret3 = p[-1] / p[-4] - 1.0

    run_min = np.minimum.accumulate(p)
    run_max = np.maximum.accumulate(p)
    major_up_seen = (p / run_min - 1.0).max() >= EVENT_MOVE_PCT
    major_down_seen = (p / run_max - 1.0).min() <= -EVENT_MOVE_PCT

    state["major_up_seen"] = state.get("major_up_seen", False) or major_up_seen
    state["major_down_seen"] = state.get("major_down_seen", False) or major_down_seen

    panic_ret = PANIC_UP_RET if (major_up_seen and (not major_down_seen)) else PANIC_DEFAULT_RET
    panic_down = (ret1 < -panic_ret) or (ret3 < -PANIC_3BAR_RET)
    if panic_down:
        return "sell", int(port.get("shares", 0) or 0)

    if major_down_seen and (ret1 > -0.01):
        qty = int((port.get("cash", 0.0) or 0.0) * POS_PCT / max(price, 1e-9))
        return "buy", max(0, qty)

    qty = int((port.get("cash", 0.0) or 0.0) * POS_PCT / max(price, 1e-9))
    return "buy", max(0, qty)

if __name__ == "__main__":
    hist = []
    state = {
        "major_up_seen": False,
        "major_down_seen": False,
        "entry_price": None,
        "peak_price": None,
    }

    print("Agent running. Ctrl+C to stop.")

    while True:
        try:
            tick = get_price()
            port = get_portfolio()
            price = as_float(tick.get("close"), 0.0)
            if price <= 0:
                print("Invalid price; skipping tick")
                time.sleep(10)
                continue

            hist.append(price)

            if tick.get("phase") == "closed":
                print("Market closed.")
                break

            shares = int(port.get("shares", 0) or 0)

            # Keep position state coherent
            if shares <= 0:
                state["entry_price"] = None
                state["peak_price"] = None
            else:
                if state.get("entry_price") is None:
                    state["entry_price"] = infer_entry_price(port, price)

                entry = as_float(state.get("entry_price"), price)
                peak_prev = as_float(state.get("peak_price"), price)
                state["entry_price"] = entry
                state["peak_price"] = max(peak_prev, price)

            # Proper live stop-loss layer
            if shares > 0 and state.get("entry_price") is not None:
                entry = as_float(state.get("entry_price"), price)
                peak = as_float(state.get("peak_price"), price)

                hard_stop_hit = price <= entry * (1.0 - STOP)
                peak_pnl = peak / max(entry, 1e-9) - 1.0
                trail_drawdown = (peak - price) / max(peak, 1e-9)
                trail_hit = (peak_pnl >= TRAIL_ARM) and (trail_drawdown >= TRAIL_GIVEBACK)

                if hard_stop_hit or trail_hit:
                    sell(shares)
                    reason = "STOP" if hard_stop_hit else "TRAIL"
                    print(
                        f"{reason} SELL {shares} @ {price:.4f} | "
                        f"entry={entry:.4f} stop={entry*(1.0-STOP):.4f} peak={peak:.4f}"
                    )
                    state["entry_price"] = None
                    state["peak_price"] = None
                    time.sleep(10)
                    continue

            action, qty = decide(hist, port, price, state)

            if action == "buy" and qty > 0 and shares == 0:
                buy(qty)
                state["entry_price"] = price
                state["peak_price"] = price
                print(f"BUY  {qty} @ {price:.4f}")
            elif action == "sell" and shares > 0:
                sell(shares)
                print(f"SELL {shares} @ {price:.4f}")
                state["entry_price"] = None
                state["peak_price"] = None
            else:
                stop_px = None
                if state.get("entry_price") is not None:
                    entry = as_float(state.get("entry_price"), price)
                    stop_px = entry * (1.0 - STOP)
                stop_txt = f" stop={stop_px:.4f}" if stop_px else ""
                print(
                    f"HOLD | {price:.4f} | pnl={port['pnl_pct']:+.2f}% | "
                    f"up_seen={state['major_up_seen']} down_seen={state['major_down_seen']}" + stop_txt
                )

        except KeyboardInterrupt:
            print("Stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(10)