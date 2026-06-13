# PROJECT: ICT MARKET STRUCTURE ENGINE

You are a senior quantitative developer and algorithmic trading engineer.

Your task is to build a fully automated ICT Market Structure Engine.

IMPORTANT:

The engine must NOT use subjective logic.

Everything must be mathematically defined.

All outputs must be machine-readable JSON.

The engine must work on:

1m
5m
15m
1H
4H
1D

---

## FOLDER STRUCTURE

ict_engine/

market_structure.py

liquidity.py

fvg.py

order_blocks.py

premium_discount.py

sessions.py

models.py

utils.py

tests/

---

## INPUT DATA

Input:

OHLCV candles

{
"timestamp":"",
"open":0,
"high":0,
"low":0,
"close":0,
"volume":0
}

Engine must process streams of candles.

---

## MARKET STRUCTURE MODULE

Build:

Swing High Detection

Swing Low Detection

Break of Structure

Change of Character

Market Structure Shift

Trend Bias

---

## SWING HIGH RULE

A swing high exists when:

Current High

>

Highest High of previous N candles

AND

Current High

>

Highest High of next N candles

Default:

N = 3

Configurable.

Output:

{
"type":"swing_high",
"price":1.2345,
"timestamp":""
}

---

## SWING LOW RULE

A swing low exists when:

Current Low

<

Lowest Low of previous N candles

AND

Current Low

<

Lowest Low of next N candles

Default:

N = 3

Output:

{
"type":"swing_low",
"price":1.2200,
"timestamp":""
}

---

## BREAK OF STRUCTURE

Bullish BOS:

Close breaks above previous confirmed swing high.

Bearish BOS:

Close breaks below previous confirmed swing low.

Output:

{
"event":"bullish_bos",
"price":1.2500
}

---

## MARKET STRUCTURE SHIFT

Bullish MSS

Conditions:

1. Previous swing low taken.
2. Price closes above recent swing high.

Bearish MSS

Conditions:

1. Previous swing high taken.
2. Price closes below recent swing low.

Output:

{
"event":"bullish_mss",
"confidence":1.0
}

---

## TREND ENGINE

Determine trend from structure.

Bullish:

HH + HL sequence

Bearish:

LL + LH sequence

Neutral:

No clear structure

Output:

{
"bias":"bullish"
}

---

## LIQUIDITY MODULE

Build detection for:

Equal Highs

Equal Lows

Previous Day High

Previous Day Low

Previous Week High

Previous Week Low

Session High

Session Low

---

## EQUAL HIGHS

Two highs considered equal when:

abs(high1-high2)

<=

ATR * 0.10

Output:

{
"type":"equal_high",
"price":1.2500
}

---

## EQUAL LOWS

Two lows considered equal when:

abs(low1-low2)

<=

ATR * 0.10

---

## LIQUIDITY SWEEP DETECTION

Bullish Sweep:

Price breaks below liquidity.

Then closes back above liquidity.

Bearish Sweep:

Price breaks above liquidity.

Then closes back below liquidity.

Output:

{
"event":"bullish_liquidity_sweep",
"price":1.2200
}

---

## FAIR VALUE GAP MODULE

Detect 3-candle imbalances.

Bullish FVG:

Candle1 High

<

Candle3 Low

Bearish FVG:

Candle1 Low

>

Candle3 High

Store:

Top

Bottom

Midpoint

Size

Status

Output:

{
"type":"bullish_fvg",
"top":1.2510,
"bottom":1.2490,
"size":20
}

---

## FVG STATUS TRACKER

Every FVG can be:

OPEN

TOUCHED

PARTIALLY FILLED

FILLED

Update status continuously.

---

## ORDER BLOCK MODULE

Build objective Order Block detection.

Avoid discretionary logic.

Bullish Order Block:

Last bearish candle

before impulse move.

Impulse Move Definition:

Move size >

2 × ATR

within next 3 candles.

Bearish Order Block:

Last bullish candle

before bearish impulse.

Output:

{
"type":"bullish_order_block",
"high":1.2450,
"low":1.2430
}

---

## ORDER BLOCK VALIDITY

Track:

UNTOUCHED

TOUCHED

MITIGATED

INVALIDATED

---

## BREAKER BLOCK MODULE

A breaker block forms when:

Order block fails.

Price breaks through.

Then retests.

Output:

{
"type":"bearish_breaker"
}

---

## PREMIUM DISCOUNT MODULE

Calculate dealing range.

Inputs:

Recent swing high

Recent swing low

Equilibrium:

(high + low)/2

Premium:

Price above equilibrium

Discount:

Price below equilibrium

Output:

{
"zone":"discount"
}

---

## OTE MODULE

Optimal Trade Entry.

Calculate:

62%
70.5%
79%

retracement levels.

Output:

{
"ote_zone":true,
"fib_level":70.5
}

---

## SESSION MODULE

Track:

Asian Session

London Session

New York Session

Store:

Session High

Session Low

Range

Output:

{
"session":"london"
}

---

## KILL ZONES

London Kill Zone

New York Kill Zone

Return:

Inside Kill Zone

True/False

---

## CONFLUENCE ENGINE

Build confluence scoring.

Example:

Bullish MSS = 20

Liquidity Sweep = 20

Bullish FVG = 15

Order Block = 15

Discount Zone = 10

OTE Zone = 10

Session Alignment = 10

Maximum:

100

Output:

{
"score":85
}

---

## MASTER SIGNAL OBJECT

Every analysis cycle must return:

{
"symbol":"EURUSD",

```
"bias":"bullish",

"market_structure":{
},

"liquidity":{
},

"fvgs":[
],

"order_blocks":[
],

"premium_discount":{
},

"confluence_score":85,

"timestamp":""
```

}

---

## PERFORMANCE

Must process:

100,000+ candles

without memory leaks.

Use:

NumPy

Pandas

Polars

where appropriate.

---

## TESTING

Create tests for:

Swing Detection

BOS

MSS

Liquidity Sweeps

FVG Detection

Order Blocks

Premium Discount

OTE

Session Logic

Target:

90%+ coverage.

---

## DOCUMENTATION

Generate detailed explanations.

Generate diagrams.

Generate examples.

Generate edge-case handling.

Generate optimization notes.

All code must be production ready.
