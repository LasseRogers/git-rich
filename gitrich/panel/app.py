import altair as alt
import pandas as pd
import streamlit as st

from gitrich.panel import data

st.set_page_config(page_title="git-rich", layout="centered")

# Categorical slot 1, stepped separately for light and dark surfaces.
LINE = "#3987e5" if st.context.theme.type == "dark" else "#2a78d6"
tz = st.context.timezone or "UTC"


def local(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert(tz)


def when(ts) -> str:
    return local(ts).strftime("%a %d %b, %H:%M")


upcoming_tab, paper_tab = st.tabs(["Upcoming", "Paper bets"])

with upcoming_tab:
    upcoming = data.upcoming_bets()
    n = len(upcoming)
    st.header(f"{n} bet{'s' if n != 1 else ''} to place" if n else "No bets right now")
    st.caption("Each match is decided 12 hours before it starts.")

    for b in upcoming.itertuples():
        with st.container(border=True):
            st.markdown(f"**Bet on {b.pick}** at odds {b.price:.2f} ({b.bookmaker})")
            st.caption(" · ".join(filter(None, [f"vs {b.opponent}", when(b.start_time), b.tournament])))
            with st.expander("Details"):
                c = st.columns(3)
                c[0].metric("Model", f"{b.p_model:.0%}", help="The model's chance this team wins.")
                c[1].metric("Bookmakers", f"{b.p_market:.0%}" if pd.notna(b.p_market) else "–",
                            help="Pinnacle's chance, with its margin removed.")
                c[2].metric("Edge", f"{b.p_model * b.price - 1:+.0%}",
                            help="Expected profit per kr staked, if the model is right.")
                stake = st.slider("Stake (kr)", 10, 1000, max(10, round(b.stake / 10) * 10), 10, key=f"stake-{b.id}",
                                  help=f"The paper bet uses {b.stake:.0f} kr.")
                st.markdown(f"Possible payout: **{stake * b.price:,.0f} kr**")

with paper_tab:
    settled = data.settled_bets()
    if settled.empty:
        st.header("No finished bets yet")
        st.caption("Results show up here once matches with paper bets have been played.")
    else:
        per_bet = st.slider("Amount per bet (kr)", 10, 1000, 20, 10)
        # The same amount on every bet, so the result only depends on which bets won and at what odds.
        pnl = per_bet * settled.price.where(settled.result == "won", 0) - per_bet
        profit = pnl.sum()
        st.header(f"{'Up' if profit >= 0 else 'Down'} {abs(profit):,.0f} kr")
        st.caption(f"{len(settled)} bets, {(settled.result == 'won').sum()} won.")

        curve = pd.DataFrame({"profit": [0.0, *pnl.cumsum()]})
        curve["n"] = curve.index
        st.altair_chart(
            alt.Chart(curve).mark_line(strokeWidth=2, color=LINE).encode(
                x=alt.X("n:Q", title="Bets", axis=alt.Axis(format="d", tickMinStep=1), scale=alt.Scale(nice=False)),
                y=alt.Y("profit:Q", title="Profit (kr)"),
                tooltip=[alt.Tooltip("n:Q", title="After bet"), alt.Tooltip("profit:Q", title="Profit", format="+,.0f")],
            ).properties(height=280),
            width="stretch",
        )

health = data.health()
updated = data.odds_updated()
st.caption(" · ".join([
    f"Model v{health['model_version']}" if health and health["model_version"] else "Prediction API not running",
    f"odds from {when(updated)}" if pd.notna(updated) else "no odds loaded",
    "paper bets, placed automatically",
]))
