# Selling a year, or half a year, up front

_Written 2026-09-12. **Nothing here is implemented.** This is the plan, the
things that have to be true before it can be built, and the one place the
current code would quietly do the wrong thing if products were added without
it._

Every Polar fact below is read from the published OpenAPI document (version
`2026-04`, the same one [`polar.py`](../backend/app/billing/providers/polar.py)
cites), not from memory. Everything marked **unverified** needs a sandbox run
before it is relied on.

---

## 0. The short version

| | |
|---|---|
| **Can Polar do annual?** | Yes. `recurring_interval: "year"`. |
| **Can Polar do half-yearly?** | Yes, and this was the open question. `recurring_interval: "month"` with `recurring_interval_count: 6`. |
| **Does it change entitlements?** | No. Not one line of `plans.py`. |
| **Does it change quota accounting?** | No. Quotas reset on the calendar month regardless. |
| **Does it change the webhook path?** | No. Already handles it correctly today. |
| **Is it safe to just add the products?** | **No.** See §2. Checkout would become ambiguous. |
| **Roughly how much work?** | One small backend change, one settings shape, and the pricing page. The prerequisites are the slow part, not the code. |

The reason this is cheap is that **cadence is a payment question and the
product is metered per calendar month**, so the two barely touch. Paying for a
year does not buy a year of messages in one bucket; it buys the same monthly
allowance, paid for in advance.

---

## 1. What is already right, and must stay right

Three things in the current code mean annual mostly works by not caring.

**Entitlements are derived from the plan, and the plan has no price.**
[`plans.py`](../backend/app/billing/plans.py) says so in its first paragraph:
prices live with the merchant of record. A plan is a contract about
allowances. An annual Growth subscription is still `growth`, with exactly the
entitlements `growth` has. No new plan keys, no duplicated quota tables.

**The webhook direction of the price map already supports many-to-one.**
`plan_for_price_id` looks a provider id up in `billing_price_map` and returns
whatever plan it names. Point three product ids — monthly, half-yearly, annual
Growth — at `"growth"` and all three resolve to the same entitlements with no
code change at all. `polar.py` anticipates exactly this: *"two products can
point at one plan"*.

**Nothing downstream measures time in subscription periods.**
`service_state` takes `current_period_end` and compares it to now
([`state.py:79`](../backend/app/billing/state.py)); it never asks how long a
period is, so a year-long one behaves correctly for free. And the message
quota is counted from `today.replace(day=1)`
([`pipeline.py:985`](../backend/app/workers/pipeline.py)) — the calendar month,
not the billing period. An annual customer's allowance still resets on the 1st,
which is the behaviour to want and the behaviour already built.

> One comment goes slightly stale: `state.py` says *"canceled keeps answering
> until the period ends. They paid for the month."* Worth amending to "the
> period" when this ships. The code is right; the sentence is narrower than the
> code.

---

## 2. The one thing that would break, and it would break silently

`polar.py` finishes that sentence with the warning: *"a plan resolving to two
prices would make checkout ambiguous."* It is not hypothetical. This is the
whole of `_price_id_for`:

```python
for price_id, mapped in (settings.billing_price_map or {}).items():
    if mapped == plan_key:
        return price_id
```

It returns **the first price that maps to the plan**. The map is a plain dict
loaded from JSON in the environment, so "first" means whatever order the
operator happened to type.

So the moment an annual Growth product is added to `QONVO_BILLING_PRICE_MAP`,
`checkout(plan_key="growth")` may start returning the annual product id. A
customer clicking a card that says **$20 a month** would be sent to a hosted
checkout for **$204 a year** — a real charge, twelve times the size, with no
error anywhere and nothing in the logs to notice. Which product wins would
depend on the order of keys in an environment variable.

**Therefore: do not add annual or half-yearly products to the price map until
§4.1 is done.** That is the blocking prerequisite, and it is the reason this
document exists rather than a dashboard walkthrough.

---

## 3. The shape to build

### 3.1 Cadence beside the plan key, never inside it

The tempting version is `PLANS["growth_annual"]`. Reject it. It duplicates
every entitlement three ways, so each future quota change becomes three edits
that must agree, and it breaks the invariant that one plan is one contract.
`subscriptions.plan_key` would also start carrying two facts in one string, and
every `== "growth"` comparison in the codebase would silently stop matching
annual customers.

Cadence is a second, independent dimension:

```
plan_key  ∈ {trial, starter, growth, scale}     what they get
cadence   ∈ {monthly, half_yearly, annual}      how often they pay
```

`plan_key` stays exactly what it is today. Cadence is new, and it is needed in
precisely one direction: **choosing a product at checkout**. The webhook
direction never needs it, because the entitlements are identical either way —
which is why §1 holds.

### 3.2 The settings change

The map stays provider-id-first, because that is the direction that must stay
authoritative for webhooks. It gains a value shape instead of a bare string:

```jsonc
// today
{"prod_abc": "growth"}

// proposed — old form still accepted, meaning monthly
{"prod_abc": "growth",
 "prod_def": {"plan": "growth", "cadence": "annual"},
 "prod_ghi": {"plan": "growth", "cadence": "half_yearly"}}
```

Accepting the bare string as "monthly" keeps every existing deployment working
without an environment edit, which matters because getting this wrong is a
billing incident rather than a 500.

### 3.3 The code change

- `plan_for_price_id` — unchanged behaviour, reads `.plan` out of either shape.
- `_price_id_for(plan_key, cadence)` — now takes both, and **returns `None`
  rather than a guess when the pair is not mapped**. A missing annual product
  must degrade to the existing "message us and we will switch it over"
  instructions path, never to a different product.
- `checkout(tenant_id, plan_key, cadence)` on the provider protocol, defaulting
  to monthly so `manual.py` and the tests need no change.
- `POST /api/billing/checkout` gains an optional `cadence`, validated against
  the enum, defaulting to monthly.
- A test that the ambiguity in §2 cannot come back: two products mapped to one
  plan, assert each cadence resolves to its own product and that an unmapped
  cadence returns `None`.

### 3.4 Switching an existing customer between cadences

`change_plan` already PATCHes `product_id`, and
`SubscriptionUpdateBase.product_id` is documented as *"Update subscription to
another product"*, so the mechanism exists.

Two cautions, one of them important:

**There is no proration preview.** `polar.py` establishes this from the same
OpenAPI document: the schemas exist, no route returns them, and the PATCH takes
no dry-run flag. Monthly-to-annual is the worst possible case for that — the
customer would be agreeing to an immediate charge of a few hundred dollars that
nobody, including us, can quote beforehand.

The fix is available and is a one-word argument. `proration_behavior` accepts
`invoice | prorate | next_period | reset`. **Send `next_period` for any cadence
change**: the switch takes effect when the current period ends, so the customer
is never surprised by an unquotable charge and the billing page can say
something true and specific ("your plan changes to yearly on 3 October").

**Whether Polar allows a product change across different recurring intervals is
unverified.** The schema does not say it is forbidden and does not say it is
allowed. Test it in the sandbox before promising it in the interface (§5).

---

## 4. Prerequisites, in order

### 4.1 Blocking — must be done before any product exists

1. Ship §3.2 and §3.3. Until `_price_id_for` is cadence-aware, adding a second
   product for a plan is a live mischarge risk.
2. The test from §3.3, so it stays fixed.

### 4.2 Blocking — commercial, and not a code question

3. **Decide the discounts** (§6 has a proposal and the arithmetic).
4. **Refunds.** Annual is where a refund request stops being trivial. Polar is
   the merchant of record and owns the refund, but the policy is ours and it
   should be written down before the first year is sold, not during the first
   argument. A pro-rata refund of unused whole months is the ordinary answer.
5. **Check the tax position.** Polar handles collection and remittance as MoR,
   so this is not a new obligation — but a year taken up front is recognised
   differently from a month, and it is worth knowing that before the volume
   makes it matter.

### 4.3 Non-blocking, but wanted before it is advertised

6. The three (or six) Polar products created in **sandbox first**, and the
   whole flow run end to end there.
7. Pricing page work (§7).
8. A decision on whether half-yearly is offered at all (§6.3).

---

## 5. The sandbox checklist

Run all of these against `polar_server=sandbox` before any of it is real. Each
one is a question the OpenAPI document does not answer.

| # | Check | Why it is on this list |
|---|---|---|
| 1 | Create a product with `recurring_interval: "month"`, `recurring_interval_count: 6` | Half-yearly is expressible in the schema; confirm the dashboard and checkout render it sanely rather than as "every 6 months" in some place a customer reads as monthly |
| 2 | Complete a checkout on the annual product | Confirm `subscription.created` carries a product id our map resolves, and that entitlements land as `growth` |
| 3 | Read `current_period_end` on that subscription | Must be ~12 months out. `service_state` depends on it |
| 4 | PATCH an active **monthly** subscription to the **annual** product | The unverified one from §3.4. If Polar refuses a cross-interval change, the interface must offer "switch at renewal" instead of a plan-change button |
| 5 | Repeat #4 with `proration_behavior: "next_period"` | The behaviour we actually want to ship |
| 6 | Cancel an annual subscription | `cancel_at_period_end` should leave a year of service. Confirm the billing page's wording is not month-shaped |
| 7 | Let a renewal fail | `subscription.past_due` → the existing 7-day grace. Seven days is a fine grace on a $17 charge and a thin one on a $576 charge; decide whether `billing_grace_days` should differ by cadence |
| 8 | Check every price the customer sees | Polar shows an annual product's price as a total, not a per-month figure. Our page will be advertising the per-month equivalent, and the two must not contradict each other at the moment of payment |

Item 8 is the one most likely to be skipped and most likely to cost a sale.

---

## 6. Discounts

### 6.1 Price the products, do not apply a coupon

Polar supports both. `DiscountPercentageCreate` takes `basis_points` (2550 =
25.5%), can be restricted to specific `products`, and has
`duration: once | forever | repeating`. That is the right tool for a
time-limited promotion.

It is the wrong tool here. The annual discount is permanent and structural — it
is the price, not a promotion on the price. Encode it as the annual product's
amount and there is one number, no coupon to leak, nothing to expire by
accident, and the customer's invoice says what the pricing page said.

Keep percentage discounts in reserve for launch offers and for the one-off
retention case.

### 6.2 The proposed ladder

Taking the steer as **10 / 15 / 20 percent, by tier**, with half-yearly at
roughly half the annual discount:

| Plan | Monthly | Half-yearly | Annual |
|---|---:|---:|---:|
| **Starter** | $10 | **$57** _(5% off, $9.50/mo)_ | **$108** _(10% off, $9.00/mo)_ |
| **Growth** | $20 | **$110** _(8.3% off, $18.33/mo)_ | **$204** _(15% off, $17.00/mo)_ |
| **Scale** | $60 | **$324** _(10% off, $54.00/mo)_ | **$576** _(20% off, $48.00/mo)_ |

Against the **worst case** cost of goods from
[UNIT-ECONOMICS.md](UNIT-ECONOMICS.md) — a tenant using every message and every
voice minute, every month — the margin holds everywhere:

| Plan | Annual, per month | Worst-case cost | Gross margin |
|---|---:|---:|---:|
| Starter | $9.00 | $1.08 | 88% |
| Growth | $17.00 | $5.25 | 69% |
| Scale | $48.00 | $21.20 | 56% |

At realistic (30%) use every one of those is above 85%. Scale at 56% on the
adversarial case is the thinnest line in the table and is still comfortable —
but it is worth noticing that **the deepest discount is on the tier with the
highest cost of goods**, which is backwards from a pure margin view. The
defence is cash: a year of Scale is $576 collected on day one against about
$254 of worst-case cost spread over twelve months.

### 6.3 Half-yearly may not be worth offering

It is expressible, so this is a product decision rather than a technical one.
Three prices per tier is nine products, nine price-map entries, and a third
column on a pricing page that already has to hold three tiers, two allowance
statements each, and a featured card.

The usual reason to want it is a customer who will not commit to a year. That
customer can also just pay monthly. **Recommendation: ship annual first,
measure how many people take it, and add half-yearly only if somebody actually
asks.** The code from §3 supports three cadences either way, so nothing is
foreclosed by waiting.

---

## 7. What the pricing page needs

[`pricing.tsx`](../dashboard/components/marketing/pricing.tsx) currently renders
three cards at one cadence.

- **A cadence toggle above the cards**, defaulting to annual with the saving
  shown, because the default is the offer most people take.
- **Show the per-month equivalent as the large number**, with the billed total
  underneath — `$17 a month, billed $204 yearly`. Never the annual total as the
  headline: $204 beside a competitor's $25 loses a comparison it should win.
- **State the saving in money as well as percent.** "Save $36" outperforms
  "15% off" for the same number.
- The allowances do not change between cadences, and the card must not imply
  they do. The lines stay identical; only the price block swaps.
- `verify:brand` forbids price figures under `app/` and allows them in
  `components/`, so this work stays where it already is.

The billing page in the dashboard needs the same cadence choice on upgrade, and
must say plainly when a cadence change takes effect (§3.4 — at renewal, not
now).

---

## 8. Open questions for a human

1. Half-yearly at all, or annual only? (§6.3 recommends annual only, for now.)
2. Is the discount ladder 10/15/20 **by tier**, as costed in §6.2 — or was it
   meant as 10% half-yearly / 15% / 20% annual across all tiers? The former is
   assumed throughout.
3. Refund policy on a part-used year (§4.2).
4. Should `billing_grace_days` be longer for annual? Seven days of grace on a
   $576 renewal is a thin window in which to lose a customer who simply changed
   card (§5, item 7).
