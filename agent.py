import os, time, requests, numpy as np

API_URL = os.getenv("API_URL", "http://SERVER_IP:8001")
API_KEY = os.getenv("TEAM_API_KEY", "YOUR_KEY_HERE")
HEADERS = {"X-API-Key": API_KEY}

POS_PCT = 1.00
STOP = 0.20
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
        return "sell", port.get("shares", 0)

    if major_down_seen and (ret1 > -0.01):
        qty = int(port.get("cash", 0.0) * POS_PCT / price)
        return "buy", max(0, qty)

    qty = int(port.get("cash", 0.0) * POS_PCT / price)
    return "buy", max(0, qty)

if __name__ == "__main__":
    hist = []
    state = {
        "major_up_seen": False,
        "major_down_seen": False,
    }

    print("Agent running. Ctrl+C to stop.")

    while True:
        try:
            tick = get_price()
            port = get_portfolio()
            price = tick["close"]
            hist.append(price)

            if tick.get("phase") == "closed":
                print("Market closed.")
                break

            action, qty = decide(hist, port, price, state)

            if action == "buy" and qty > 0 and port.get("shares", 0) == 0:
                buy(qty)
                print(f"BUY  {qty} @ {price:.4f}")
            elif action == "sell" and port.get("shares", 0) > 0:
                sell(port["shares"])
                print(f"SELL {port['shares']} @ {price:.4f}")
            else:
                print(
                    f"HOLD | {price:.4f} | pnl={port['pnl_pct']:+.2f}% | "
                    f"up_seen={state['major_up_seen']} down_seen={state['major_down_seen']}"
                )

        except KeyboardInterrupt:
            print("Stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(10)